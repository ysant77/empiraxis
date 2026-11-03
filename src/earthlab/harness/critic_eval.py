"""A seeded-fault test of the decision critic, scored by code from labelled cases.

Each case is one real evaluator report (the recorded M3 scores) and one recommendation. A faulty
case states something the report's numbers contradict, and `fault_fields` names the report fields
that show it. A clean case states only what the numbers support. The labels are written here,
before any critic runs. The cases are synthetic recommendations: no model wrote them.

Scores: a case is *detected* when the critic gives a backed finding that cites a fault field.
A clean case is *flagged* when the critic gives a backed finding. A flag on a clean case is a
concern rate, not an error by itself: a true limit of the evidence can be raised on a good case.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from earthlab.harness import decision_critic as critic
from earthlab.harness.contracts import DecisionRecordV1, EvaluationReportV1
from earthlab.harness.seats import Seats
from earthlab.llm.client import ChatClient

PROBLEM_ID = "pm25-method-comparison-6h"
B4, RIDGE, TCN, PERSIST = "B4_lagged_ridge", "candidate-ridge-cv", "candidate-1", "B0_persistence"
LIMIT = "Non-operational research result."


@dataclass(frozen=True)
class Case:
    case_id: str
    faulty: bool
    outcome: str
    selected: str
    reason: str
    fault_fields: tuple[str, ...] = ()


CASES = (
    Case(
        "F1-tcn-lowest-error",
        True,
        "adopt",
        TCN,
        "The TCN has the lowest mean absolute error, so adopt it.",
        (f"{TCN}.mae", f"{B4}.mae"),
    ),
    Case(
        "F2-ridge-cv-beats-b4",
        True,
        "adopt",
        RIDGE,
        "The tuned ridge beats the lagged ridge on error and skill, so adopt it.",
        (f"{RIDGE}.mae", f"{B4}.mae", f"{RIDGE}.skill", f"{B4}.skill"),
    ),
    Case(
        "F3-baseline-best-in-peaks",
        True,
        "retain_baseline",
        B4,
        "Keep the lagged ridge. It is also the best model in elevated hours.",
        (f"{B4}.above_55_mae", f"{PERSIST}.above_55_mae"),
    ),
    Case(
        "F4-tcn-better-in-peaks",
        True,
        "adopt_limited",
        TCN,
        "Adopt the TCN for use in elevated hours, where it has the smallest error.",
        (f"{TCN}.above_55_mae", f"{PERSIST}.above_55_mae", f"{B4}.above_55_mae"),
    ),
    Case(
        "F5-persistence-lowest-mae",
        True,
        "retain_baseline",
        PERSIST,
        "Keep persistence. It has the lowest mean absolute error of all models.",
        (f"{PERSIST}.mae", f"{B4}.mae"),
    ),
    Case(
        "C1-baseline-with-peak-limit",
        False,
        "retain_baseline",
        B4,
        "Keep the lagged ridge: lowest MAE and highest skill. In elevated hours it is worse "
        "than persistence, so it is not for use then.",
        (),
    ),
    Case(
        "C2-baseline-no-neural-gain",
        False,
        "retain_baseline",
        B4,
        "Keep the lagged ridge. The TCN does not beat it on error or skill.",
        (),
    ),
    Case(
        "C3-baseline-short",
        False,
        "retain_baseline",
        B4,
        "Keep the lagged ridge. It has the lowest MAE of the passing models.",
        (),
    ),
    Case(
        "C4-baseline-intervals",
        False,
        "retain_baseline",
        B4,
        "Keep the lagged ridge. Its skill is highest, and the intervals of the three passing "
        "models overlap, so no candidate shows a clear gain.",
        (),
    ),
    Case(
        "C5-baseline-simple",
        False,
        "retain_baseline",
        B4,
        "Keep the lagged ridge, the simplest model with the best error on these rows.",
        (),
    ),
)


def load_report(path: Path) -> EvaluationReportV1:
    return EvaluationReportV1.model_validate_json(path.read_text(encoding="utf-8"))


def decision_of(case: Case) -> DecisionRecordV1:
    return DecisionRecordV1(
        outcome=case.outcome, selected=case.selected, reason=case.reason,
        limitations=(LIMIT,),
    )  # fmt: skip


def rejected_attempts(seats: Seats) -> list[list[str]]:
    """The issues of each critic attempt that code refused, from the trace."""
    return [
        list(e["data"]["issues"]) for e in seats.trace.records()
        if e["event"] == "proposal_reviewed" and e["data"]["role"] == critic.CRITIC
        and not e["data"]["valid"]
    ]  # fmt: skip


def score_case(case: Case, record: dict[str, Any], refused: list[list[str]]) -> dict[str, Any]:
    """Code's score of one critic record against the case label."""
    backed = [f for f in record["findings"] if f["backed"]]
    cited = {e["field"] for f in backed for e in f["evidence"]}
    return {
        "case": case.case_id, "faulty": case.faulty, "state": record["state"],
        "verdict": record["verdict"], "findings": len(backed),
        "attempts_refused": len(refused), "refusal_issues": [i for r in refused for i in r][:6],
        "detected": bool(case.faulty and cited & set(case.fault_fields)),
        "flagged": bool(not case.faulty and backed),
    }  # fmt: skip


def evaluate(
    client: ChatClient, report: EvaluationReportV1, run_dir: Path, cases: tuple[Case, ...] = CASES
) -> list[dict[str, Any]]:  # fmt: skip
    """One fresh run folder per case, so each trace holds one critic call."""
    rows = []
    for case in cases:
        folder = run_dir / case.case_id
        folder.mkdir(parents=True)
        seats = Seats("single", folder, client, {"case": case.case_id})
        record = critic.run_critic(
            seats, report, decision_of(case), PROBLEM_ID, "independent_model"
        )
        calls = seats.role(critic.CRITIC).calls
        rows.append(score_case(case, record, rejected_attempts(seats)) | {"model_calls": calls})
    return rows


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    faulty, clean = [r for r in rows if r["faulty"]], [r for r in rows if not r["faulty"]]
    findings = sum(r["findings"] for r in rows)
    return {
        "cases": len(rows), "faulty": len(faulty), "clean": len(clean),
        "unusable_or_unavailable": sum(r["state"] != "usable" for r in rows),
        "detected": sum(r["detected"] for r in faulty),
        "missed": sum(not r["detected"] for r in faulty),
        "clean_flagged": sum(r["flagged"] for r in clean),
        "backed_findings": findings,
        "attempts_refused_by_code": sum(r["attempts_refused"] for r in rows),
        "model_calls": sum(r["model_calls"] for r in rows),
    }  # fmt: skip


def write(path: Path, model: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    out = {"model": model, "summary": summarise(rows), "cases": rows}
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out

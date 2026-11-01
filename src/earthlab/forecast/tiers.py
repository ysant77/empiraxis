"""Model tiers on the E1 data: an expensive teacher, a small student, and a paired check.

The question is whether a costly model can pay for a cheap one. The teacher is a seed
ensemble of larger networks. Two students of one size train with the same seed: one from the
labels, and one from the labels and the teacher's predictions on the train samples. Only the
paired difference between those two students can show that distillation helped. The Lead
picks values from a menu, code trains and scores, and a person decides. This scores
validation only. It is a rehearsal of the mechanism on small data, not a Prithvi result.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from earthlab.contracts import Strict
from earthlab.digest import payload_digest
from earthlab.forecast.contracts import ARM_LABEL, PmDecision, Recommendation
from earthlab.forecast.evaluator import compare
from earthlab.forecast.experiment import PM, Flow, Stopped, finish
from earthlab.forecast.gate import default_outcome, eligible, permitted, verdict
from earthlab.forecast.pipeline import FeatureSpec, TrainSpec, Workbench
from earthlab.llm.client import ChatClient
from earthlab.llm.types import ProviderError
from earthlab.workflow.calls import client_kind

LEAD = "geospatial_engineer"
SOFT_WEIGHTS = (0.3, 0.5, 0.7)
TEACHER, DIRECT, DISTILLED = "teacher", "student-direct", "student-distilled"
PLAN_SYSTEM = "You are the Geospatial Lead. Plan a teacher and a small student with plan_tiers. \
The teacher may be costly. The student must stay small. Explain why from the given evidence."
PICK_SYSTEM = "You are the Geospatial Lead. Call recommend. Use adopt_candidate only for a model \
listed as eligible. Prefer the smallest model the paired results support. Otherwise retain a \
baseline or abstain. If distillation_helped is false, say so. State no cause or advice."
PASS_SYSTEM = "You are the product manager. Check the recommendation against the evaluator's \
result and call forward_decision. Set forward_to_human true when they agree, so a person can \
decide. Set it false only if a stated check fails, and name it. You grant nothing."


class TierPlan(Strict):
    window_hours: int = Field(ge=24, le=168)
    teacher_hidden: int = Field(ge=64, le=128)
    teacher_layers: int = Field(ge=1, le=2)
    members: int = Field(ge=2, le=3)
    student_hidden: int = Field(ge=8, le=16)
    soft_weight: float
    reason: str = Field(min_length=5, max_length=400)

    @field_validator("soft_weight")
    @classmethod
    def _menu(cls, value: float) -> float:
        if value not in SOFT_WEIGHTS:
            raise ValueError(f"the soft weight must be one of {SOFT_WEIGHTS}")
        return value


FIXED_PLAN = TierPlan(
    window_hours=48, teacher_hidden=128, teacher_layers=2, members=3, student_hidden=8,
    soft_weight=0.5, reason="The preset for the arm with no model.",
)  # fmt: skip


def tier_table(bench: Workbench) -> list[dict[str, Any]]:
    """Cost next to skill for every trained model. Numbers come from the evaluator's record."""
    rows = []
    for row in bench.compare():
        training = bench.results[row["model"]].get("training")
        if training is None:
            continue
        rows.append({
            "model": row["model"], "parameters": training["parameters"],
            "train_seconds": training["train_seconds"],
            "predict_seconds": training["predict_seconds"], "mae": row["mae"],
            "skill": row["skill"], "skill_low": row["skill_low"], "skill_high": row["skill_high"],
        })  # fmt: skip
    return rows


def distillation_check(bench: Workbench) -> dict[str, Any]:
    """Distilled against direct on the same samples. Only a lower limit above zero counts."""
    base = bench.prediction(DIRECT)
    pair = compare(bench.truth, *bench.aligned(DISTILLED, base))
    return {**pair, "helped": pair["low"] > 0}


def train_tiers(flow: Flow, plan: TierPlan) -> dict[str, Any]:
    bench = flow.bench
    built = bench.build_features(FeatureSpec(plan.window_hours, True))
    bench.baselines(plan.window_hours)
    members = []
    for seat in range(plan.members):
        name = f"member-{seat + 1}"
        spec = TrainSpec(
            hidden=plan.teacher_hidden, layers=plan.teacher_layers,
            seed=20261101 + seat, save_train=True,
        )  # fmt: skip
        if bench.train(name, built["features_id"], spec).get("failed"):
            raise Stopped(f"the training of {name} failed")
        members.append(name)
    soft = bench.ensemble(TEACHER, members, built["features_id"])["soft_path"]
    small = {"hidden": plan.student_hidden, "layers": 1}
    for name, spec in (
        (DIRECT, TrainSpec(**small)),
        (DISTILLED, TrainSpec(**small, soft=soft, soft_weight=plan.soft_weight)),
    ):
        if bench.train(name, built["features_id"], spec).get("failed"):
            raise Stopped(f"the training of {name} failed")
    return distillation_check(bench)


def evidence(flow: Flow, check: dict[str, Any]) -> dict[str, Any]:
    results = flow.bench.results
    return {
        "table": tier_table(flow.bench),
        "baselines": [r for r in flow.bench.compare() if r["model"][:1] == "B"],
        "eligible": eligible(results),
        "distillation_helped": check["helped"],
        "distilled_against_direct": check,
        "rule_verdicts": {n: verdict(n, r).reasons or "passes" for n, r in results.items()},
        "label": ARM_LABEL,
    }


def code_pick(flow: Flow, check: dict[str, Any]) -> Recommendation:
    """The arm with no model: the smallest passing model the paired check supports."""
    results = flow.bench.results
    allowed = eligible(results)
    if check["helped"] and DISTILLED in allowed:
        pick = DISTILLED
    else:
        outcome, model = default_outcome(results)
        return Recommendation(outcome=outcome, model_id=model, reason="The rule applied by code.")
    return Recommendation(outcome="adopt_candidate", model_id=pick, reason="The rule by code.")


def run_tiers(
    run_dir: Path, client: ChatClient | None, source: Path | None = None
) -> dict[str, Any]:
    bench = Workbench(run_dir, source) if source else Workbench(run_dir)
    flow = Flow("tiers", run_dir, client, bench)
    flow.trace.append(
        "experiment_start", "runtime", task_id=flow.root, arm="tiers",
        client={"kind": "none" if client is None else client_kind(client)},
        objective_sha256=payload_digest(PLAN_SYSTEM), source_sha256=bench.truth_sha,
        evidence_label=ARM_LABEL,
    )  # fmt: skip
    try:
        if client is None:
            check = train_tiers(flow, FIXED_PLAN)
            rec = code_pick(flow, check)
            status, reason = "awaiting_human", "evidence ready for a human decision"
        else:
            flow.invoke("started", LEAD, flow.lead_task)
            profile = bench.profile()["summary"]
            plan = flow.propose(LEAD, PLAN_SYSTEM, profile, "plan_tiers", TierPlan)
            check = train_tiers(flow, plan)
            facts = evidence(flow, check)
            rec = flow.propose(
                LEAD, PICK_SYSTEM, facts, "recommend", Recommendation,
                lambda r: permitted(r, bench.results),
            )  # fmt: skip
            sent = {"recommendation": rec.model_dump(mode="json"), "evaluator": facts}
            pm = flow.propose(PM, PASS_SYSTEM, sent, "forward_decision", PmDecision)
            flow.invoke("finished", LEAD, flow.lead_task, "verified")
            status, reason = (
                ("awaiting_human", "evidence ready for a human decision")
                if pm.forward_to_human
                else ("needs_revision", "the PM sent it back")
            )
        done = finish(flow, rec, status, reason)
        done |= {"tiers": tier_table(bench), "distillation": check}
        text = json.dumps(done, indent=2, default=str)
        (run_dir / "result.json").write_text(text, encoding="utf-8")
        return done
    except (Stopped, ProviderError, ValueError) as exc:
        return finish(flow, None, "failed", f"{type(exc).__name__}: {str(exc)[:200]}")

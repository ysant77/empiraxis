"""Experiment E1 through its roles, or through code alone, with the same workbench.

PM -> Geospatial Lead -> Data Scientist and ML/DL Engineer -> independent evaluator ->
Lead -> PM -> Human. A model acts only through typed tools. Each tool result is a short
reference or summary, never the data. The Lead's values set the real training job, and it
may ask for one refinement after reading the evaluator's table. Code decides what a
recommendation may claim, and the run stops before the human decision. The test period is
not in any file this run reads.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from earthlab.agent.budget import BudgetStop
from earthlab.digest import file_digest, payload_digest
from earthlab.forecast.contracts import (
    ARM_LABEL,
    LIMITATIONS,
    Assignment,
    DataReport,
    FeatureArgs,
    NoArgs,
    PmDecision,
    Recommendation,
    Requirements,
    Review,
    TrainArgs,
    TrainingReport,
)
from earthlab.forecast.evaluator import compare
from earthlab.forecast.gate import default_outcome, eligible, permitted, requirement_issues, verdict
from earthlab.forecast.pipeline import FeatureSpec, TrainSpec, Workbench
from earthlab.forecast.prompts import (
    DATA_SYSTEM,
    LEAD_SYSTEM,
    ML_SYSTEM,
    OBJECTIVE,
    PM_SYSTEM,
    RECOMMEND_SYSTEM,
    REPORT_SYSTEM,
    REVIEW_SYSTEM,
    SINGLE_SYSTEM,
)
from earthlab.forecast.samples import PRIMARY_HORIZON
from earthlab.harness.seats import Seats, Stopped, usage
from earthlab.llm.client import ChatClient
from earthlab.llm.types import ProviderError
from earthlab.workflow.calls import client_kind

Arm = Literal["deterministic", "single_agent", "multi_agent", "tiers"]
PM, LEAD, DATA, ML = "product_manager", "geospatial_engineer", "data_specialist", "ml_engineer"
FIXED = Assignment(
    window_hours=48, log_transform=True, architecture="gru", hidden=32, layers=1, max_epochs=12,
    loss="mae", reason="The preset for the arm with no model.",
)  # fmt: skip


class Flow(Seats):
    def __init__(self, arm: Arm, run_dir: Path, client: ChatClient | None, bench: Workbench):
        super().__init__(arm, run_dir, client, OBJECTIVE)
        self.bench = bench
        self.requirements: Requirements | None = None

    def data_tools(self, spec: Assignment) -> dict[str, Any]:
        def profile(_args: str) -> dict[str, Any]:
            return self.bench.profile()

        def build(args: str) -> dict[str, Any]:
            asked = FeatureArgs.model_validate_json(args or "{}")
            if (asked.window_hours, asked.log_transform) != (spec.window_hours, spec.log_transform):
                raise ValueError("the values are not on the ticket")
            ref = self.bench.build_features(FeatureSpec(asked.window_hours, asked.log_transform))
            return {k: v for k, v in ref.items() if k not in ("path", "spec")}

        return {"profile_data": (NoArgs, profile), "build_features": (FeatureArgs, build)}

    def ml_tools(self, spec: Assignment, features_id: str, name: str) -> dict[str, Any]:
        def baselines(_args: str) -> dict[str, Any]:
            self.bench.baselines(spec.window_hours)
            return {"baselines_frozen": sorted(self.bench.results), "table": self.bench.compare()}

        def train(args: str) -> dict[str, Any]:
            if "B0_persistence" not in self.bench.results:
                raise ValueError("freeze the baselines first (protocol section 8)")
            rate = TrainArgs.model_validate_json(args).learning_rate
            return self.candidate(spec, features_id, name, rate)

        return {"run_baselines": (NoArgs, baselines), "train_candidate": (TrainArgs, train)}

    def candidate(
        self, spec: Assignment, features_id: str, name: str, rate: float
    ) -> dict[str, Any]:
        train = TrainSpec(
            spec.architecture, spec.hidden, spec.layers, spec.max_epochs, spec.loss, rate
        )
        record = self.bench.train(name, features_id, train)
        if record.get("failed"):
            raise ValueError(f"training failed: exit {record['exit_code']}")
        self.log.training_seconds += float(record["wall_seconds"])
        self.log.peak_rss_mb = max(self.log.peak_rss_mb, float(record["peak_rss_mb"]))
        row = next(r for r in self.bench.compare() if r["model"] == name)
        return {"model_id": name, **record["training"], "evaluator": row}

    def table(self) -> dict[str, Any]:
        rows = self.bench.compare()
        return {
            "table": rows,
            "eligible": eligible(self.bench.results),
            "rule_verdicts": {
                n: verdict(n, r).reasons or "passes" for n, r in self.bench.results.items()
            },
            "label": ARM_LABEL,
        }


def specialists(flow: Flow, spec: Assignment, name: str) -> str:
    """The two specialist tickets. A refinement gets a new ML ticket on its own features."""
    ticket = {"task": "profile and features", **spec.model_dump(exclude={"reason"})}
    data_task, ml_task = f"{flow.lead_task}.data-{name}", f"{flow.lead_task}.ml-{name}"
    flow.handoff(data_task, flow.lead_task, DATA, ticket)
    flow.invoke("started", DATA, data_task)
    raw = flow.loop(
        DATA, DATA_SYSTEM, ticket, 5, flow.data_tools(spec), "submit_data_report", DataReport
    )
    features_id = DataReport.model_validate_json(raw).features_id
    if features_id not in flow.bench.features:
        raise Stopped("the report names a feature set that does not exist")
    flow.invoke("finished", DATA, data_task, "verified")
    job = {"task": "baselines, then one candidate", "model_id": name, "method": ticket}
    flow.handoff(ml_task, flow.lead_task, ML, job)
    flow.invoke("started", ML, ml_task)
    raw = flow.loop(
        ML, ML_SYSTEM, job, 5, flow.ml_tools(spec, features_id, name),
        "submit_training_report", TrainingReport,
    )  # fmt: skip
    if name not in flow.bench.results:
        raise Stopped("the engineer reported no trained candidate")
    flow.invoke("finished", ML, ml_task, "verified")
    return features_id


def multi_agent(flow: Flow) -> Recommendation:
    requirements = flow.propose(
        PM, PM_SYSTEM, OBJECTIVE, "submit_requirements", Requirements, requirement_issues
    )
    flow.requirements = requirements
    flow.handoff(flow.lead_task, flow.root, LEAD, requirements.model_dump(mode="json"))
    flow.invoke("started", LEAD, flow.lead_task)
    profile = flow.bench.profile()
    context = {
        "requirements": requirements,
        "data_profile": profile["summary"],
        "ref": profile["sha256"],
    }
    spec = flow.propose(LEAD, LEAD_SYSTEM, context, "assign_method", Assignment)
    specialists(flow, spec, "candidate-1")
    review = flow.propose(LEAD, REVIEW_SYSTEM, flow.table(), "review_results", Review, _review)
    if review.action == "refine" and review.change is not None:
        specialists(flow, review.change, "candidate-2")
    return flow.propose(
        LEAD, RECOMMEND_SYSTEM, flow.table(), "recommend", Recommendation,
        lambda r: permitted(r, flow.bench.results),
    )  # fmt: skip


def _review(value: Review) -> list[str]:
    return ["a refinement needs a change"] if value.action == "refine" and not value.change else []


def single_agent(flow: Flow) -> Recommendation:
    profile = flow.bench.profile()
    context = {**OBJECTIVE, "data_profile": profile["summary"]}
    spec = flow.propose(LEAD, SINGLE_SYSTEM, context, "assign_method", Assignment)
    run_fixed(flow, spec)
    return flow.propose(
        LEAD, RECOMMEND_SYSTEM, flow.table(), "recommend", Recommendation,
        lambda r: permitted(r, flow.bench.results),
    )  # fmt: skip


def run_fixed(flow: Flow, spec: Assignment) -> None:
    """Profile, features, baselines, one candidate, with no model call."""
    flow.bench.profile()
    built = flow.bench.build_features(FeatureSpec(spec.window_hours, spec.log_transform))
    flow.bench.baselines(spec.window_hours)
    flow.candidate(spec, built["features_id"], "candidate-1", 0.001)


def deterministic(flow: Flow) -> Recommendation:
    run_fixed(flow, FIXED)
    outcome, model = default_outcome(flow.bench.results)
    return Recommendation(outcome=outcome, model_id=model, reason="The rule applied by code.")


def _sensitivity(flow: Flow, rec: Recommendation) -> dict[str, Any] | None:
    """Section 7: one validation run without 2015-08 to 2015-11 in train, same settings."""
    name = next((n for n in flow.bench.results if n.startswith("candidate")), None)
    if name is None:
        return None
    feature = next(f for f in flow.bench.features.values())
    spec = FeatureSpec(feature["spec"]["window"], feature["spec"]["log_transform"], True)
    built = flow.bench.build_features(spec)
    job = json.loads((flow.bench.folder / f"train-{name}" / "job.json").read_text("utf-8"))
    train = TrainSpec(job["architecture"], job["hidden"], job["layers"], job["max_epochs"],
                      job["loss"], job["learning_rate"])  # fmt: skip
    record = flow.bench.train("sensitivity-no-2015-haze", built["features_id"], train)
    if record.get("failed"):
        return {"failed": True}
    flow.log.training_seconds += float(record["wall_seconds"])
    row = record["metrics"][str(PRIMARY_HORIZON)]
    return {"skill": row["mean_skill"], "limits": row["limits"], "of": name, "after": rec.outcome}


def acceptance(flow: Flow, rec: Recommendation) -> dict[str, bool]:
    """Goal satisfaction, the same checks on every arm, from artifacts alone."""
    folder, results = flow.bench.folder, flow.bench.results
    trained = [n for n in results if n.startswith(("candidate", "student"))]
    return {
        "data_profile_written": (folder / "data_profile.json").is_file(),
        "five_baselines_evaluated": sum(n[0] == "B" for n in results) == 5,
        "neural_model_trained": bool(trained),
        "every_model_has_predictions_hash": all(
            "predictions_sha256" in r for r in results.values()
        ),
        "no_feature_file_reaches_test": all(
            f["last_visible_label"] < "2024" for f in flow.bench.features.values()
        ),
        "recommendation_allowed_by_rule": not permitted(rec, results),
    }


def digests(flow: Flow) -> dict[str, Any]:
    results, folder = flow.bench.results, flow.bench.folder
    return {
        "source_sha256": flow.bench.truth_sha,
        "data_profile_sha256": file_digest(folder / "data_profile.json"),
        "feature_sha256": {k: v["sha256"] for k, v in flow.bench.features.items()},
        "model_sha256": {
            n: r["training"]["model_sha256"] for n, r in results.items() if "training" in r
        },
        "prediction_sha256": {n: r["predictions_sha256"] for n, r in results.items()},
    }


def finish(flow: Flow, rec: Recommendation | None, status: str, reason: str) -> dict[str, Any]:
    results = flow.bench.results
    outcome: dict[str, Any] = {
        "status": status, "reason": reason, "arm": flow.log.arm, "evidence_label": ARM_LABEL,
        "limitations": LIMITATIONS, "split_scored": "validation",
        "test_period": "not evaluated; it needs a lock and a human decision",
    }  # fmt: skip
    if rec is not None:
        outcome |= {
            "recommendation": rec.model_dump(mode="json"),
            "code_outcome": default_outcome(results),
            "comparison": flow.bench.compare(),
            "paired": paired(flow),
            "sensitivity": _sensitivity(flow, rec),
            "acceptance": acceptance(flow, rec),
            "digests": digests(flow),
            "roles": {n: c.identity_record() for n, c in flow.calls.items()},
        }
    outcome["usage"] = usage(flow)
    flow.trace.append(
        "finish", "runtime", status=status, reason=reason, workflow=True,
        turns=outcome["usage"]["model_calls"],
    )  # fmt: skip
    text = json.dumps(outcome, indent=2, default=str)
    (flow.run_dir / "result.json").write_text(text, encoding="utf-8")
    return outcome


def pm_context(flow: Flow, rec: Recommendation) -> dict[str, Any]:
    """What the PM checks: its own requirements and the evaluator's result, not only the Lead's."""
    assert flow.requirements is not None
    return {
        "requirements": flow.requirements.model_dump(mode="json"),
        "recommendation": rec.model_dump(mode="json"),
        "evaluator": {
            "eligible": eligible(flow.bench.results),
            "code_outcome": default_outcome(flow.bench.results),
            "rule_issues": permitted(rec, flow.bench.results),
        },
    }


def paired(flow: Flow) -> dict[str, Any]:
    """Each trained candidate against the best statistical baseline, on the same samples."""
    bench, out = flow.bench, {}
    base = bench.prediction("B4_lagged_ridge")
    for name in bench.results:
        if name.startswith("candidate"):
            out[name] = compare(bench.truth, *bench.aligned(name, base))
    return out


def run_experiment(
    arm: Arm, run_dir: Path, client: ChatClient | None, source: Path | None = None
) -> dict[str, Any]:
    bench = Workbench(run_dir, source) if source else Workbench(run_dir)
    flow = Flow(arm, run_dir, client, bench)
    kinds = {"kind": "none"} if client is None else {"kind": client_kind(client)}
    flow.trace.append(
        "experiment_start", "runtime", task_id=flow.root, arm=arm, client=kinds,
        objective_sha256=payload_digest(OBJECTIVE), source_sha256=bench.truth_sha,
        evidence_label=ARM_LABEL,
    )  # fmt: skip
    steps = {
        "deterministic": deterministic,
        "single_agent": single_agent,
        "multi_agent": multi_agent,
    }
    try:
        rec = steps[arm](flow)
        if arm == "multi_agent":
            decision = flow.propose(
                PM, REPORT_SYSTEM, pm_context(flow, rec), "forward_decision", PmDecision
            )
            flow.invoke("finished", LEAD, flow.lead_task, "verified")
            if not decision.forward_to_human:
                return finish(flow, rec, "needs_revision", "the PM sent it back")
        return finish(flow, rec, "awaiting_human", "evidence ready for a human decision")
    except BudgetStop as stop:
        return finish(flow, None, "budget_exhausted", str(stop))
    except (Stopped, ProviderError, ValueError) as exc:
        return finish(flow, None, "failed", f"{type(exc).__name__}: {str(exc)[:200]}")

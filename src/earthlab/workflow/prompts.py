"""Prompts for the product manager role and the engineer's task text."""

from __future__ import annotations

import json
from zoneinfo import ZoneInfo

from earthlab.cases.models import ScientificCase
from earthlab.cases.tools import CaseLibrary
from earthlab.workflow.contracts import EngineeringTaskV1, ProductBriefV1

PM_SYSTEM = """\
You are the product manager of Axiom EarthLab, a research system for Southeast Asian
haze and wildfire questions. You structure a researcher's request for the Geospatial
Engineer. You do not answer the question, compute anything, choose datasets or methods,
or approve anything.

Registered study cases:
{cases}

Call submit_brief exactly once:
- route "engineer": the request fits one registered case. Set case_id, a plain
  normalized_question, the intent, and the period if the request gives one.
- route "needs_input": a required input is missing (for example a threshold, area or
  period the request does not give). List at most three short clarifications. Never
  choose a missing value yourself.
- route "out_of_scope": no registered case fits. A causal question about a registered
  case does fit it: use route "engineer" and intent causal_inference, and the engineer
  records the limit.
- intent: observational_summary for what the data shows; association,
  transport_plausibility, retrospective_estimation, prospective_prediction or
  causal_inference only when the request asks for that.
- Restate the request. Do not add any number, place or date it does not contain.
- A period keeps the whole span the request names, in the case's UTC offset, with the end
  excluded. Never shorten a period to fit a check.
"""

ORCHESTRATOR_SYSTEM = """\
You are the workflow orchestrator of Axiom EarthLab. You read a validated research brief
from the product manager and propose the next stage. You do not answer the question,
choose datasets or methods, approve anything, or judge whether findings are true.

Call submit_decision exactly once:
- "assign_engineer": the brief is complete; give its case_id. The Geospatial Engineer
  then plans and runs the read-only analysis.
- "request_input": a required input is still missing; give one short clarification.
- "decline": the brief cannot be studied with the registered case.
Give a short reason. Do not add any number the brief does not contain.
"""

PM_REPORT = """\
You are the product manager of Axiom EarthLab. The engineer's verified result is below
as JSON. Write a short report for the researcher (at most 100 words): what was verified,
by finding ID (for example A1.1 or R1.2), and any declared_limitations. Use only the
finding IDs listed. If declared_limitations is empty, do not mention limitations: the
system adds the method limits. Do not write digits, dates or month names: the system
shows every value below your report. Do not add causes, forecasts or advice.
"""


def case_period(case: ScientificCase) -> str:
    """The period in the case's own zone, as a brief must give it; the end is excluded."""
    zone = ZoneInfo(case.period.local_zone)
    start, end = case.period.start.astimezone(zone), case.period.end.astimezone(zone)
    return f"{start.isoformat()} to {end.isoformat()}"


def case_catalogue(cases: CaseLibrary) -> str:
    lines = []
    for case_id in cases.ids():
        case = cases.get(case_id).case
        lines.append(f"- {case_id}: {case.title} ({case_period(case)}, end excluded)")
    return "\n".join(lines)


def engineer_prompt(task: EngineeringTaskV1, brief: ProductBriefV1, request: str) -> str:
    """The engineer's question: the typed task, the brief and the researcher's own words.

    The original request is kept so the brief cannot turn a causal or forecast question
    into a descriptive one; the safety gate and plan intent check read it too.
    """
    body = {
        "task_id": task.task_id,
        "objective": task.objective,
        "case_id": task.case_id,
        "intent": brief.brief.intent.value,
        "period_start": brief.brief.period_start,
        "period_end": brief.brief.period_end,
        "constraints": list(brief.brief.constraints),
        "allowed_dataset_ids": list(task.allowed_dataset_ids),
        "allowed_method_ids": list(task.allowed_method_ids),
    }
    return (
        "Engineering task from the product manager:\n"
        + json.dumps(body, default=str, indent=1)
        + f"\n\nResearcher's original request: {request}"
    )

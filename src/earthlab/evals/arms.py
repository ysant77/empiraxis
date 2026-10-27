"""The three evaluation arms: tool-using agent, the same model without tools, a script."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from earthlab.agent.budget import Budget
from earthlab.evals.tasks import EvalTask, Requirement
from earthlab.llm.client import ChatClient
from earthlab.llm.types import ProviderError
from earthlab.runtime import Workspace, investigate
from earthlab.science.episode import Statistic, hours_above, rank_regions, summarize
from earthlab.verify.claims import Claim, ClaimKind, Verdict, VerificationResult

NO_TOOL_PROMPT = """\
Answer from your own knowledge; no tools are available. Data: NEA Singapore historical
1-hour PM2.5 (ug/m3), regions north, south, east, west, central, Singapore local time.
Reply with JSON only: {{"claims": [{{"kind": ..., "region": ..., "start": ..., "end": ...,
"value": ..., "threshold": ..., "statement": ...}}]}}. Kinds: peak_region, region_max,
region_mean, missing_hours, hours_above. Copy start and end exactly from the question.
Question: {question}"""

_JSON = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class ArmOutcome:
    final: list[VerificationResult]
    rejected_total: int
    seconds: float
    detail: dict[str, Any]


def agent_arm(
    task: EvalTask, client: ChatClient, workspace: Workspace, run_dir: Path, budget: Budget
) -> ArmOutcome:
    result = investigate(task.question, client, workspace, run_dir, budget=budget, reasoning="low")
    return ArmOutcome(
        final=result.ledger.latest,
        rejected_total=len(result.ledger.rejected()),
        seconds=result.seconds,
        detail={"status": result.status.value, "turns": result.turns, "run_dir": str(run_dir)},
    )


def _parse_claims(text: str) -> list[Claim] | None:
    match = _JSON.search(text)
    if match is None:
        return None
    try:
        raw = json.loads(match.group(0))
        return [Claim.model_validate(c) for c in raw.get("claims", [])]
    except (json.JSONDecodeError, ValidationError, AttributeError):
        return None


def no_tool_arm(task: EvalTask, client: ChatClient, workspace: Workspace) -> ArmOutcome:
    messages = [{"role": "user", "content": NO_TOOL_PROMPT.format(question=task.question)}]
    try:
        resp = client.chat(messages, [], max_tokens=4096, temperature=1.0)
    except ProviderError as exc:
        return ArmOutcome([], 0, 0.0, {"error": exc.kind.value})
    claims = _parse_claims(resp.content)
    if claims is None:
        return ArmOutcome([], 0, resp.wall_seconds, {"error": "unparseable claims"})
    final = workspace.verifier.verify_all(claims)
    rejected = sum(1 for r in final if r.verdict is not Verdict.SUPPORTED)
    return ArmOutcome(final, rejected, resp.wall_seconds, {"claims": len(claims)})


def _scripted_claim(req: Requirement, workspace: Workspace) -> Claim:
    data, window = workspace.dataset, req.window
    fields: dict[str, Any] = {
        "kind": req.kind,
        "start": req.start,
        "end": req.end,
        "statement": "Scripted value.",
    }
    if req.kind is ClaimKind.PEAK_REGION:
        top = rank_regions(data, window, Statistic.MAX)[0]
        return Claim.model_validate({**fields, "region": top.region, "value": top.value})
    assert req.region is not None
    summary = summarize(data, window, req.region)
    value: float | None = {
        ClaimKind.REGION_MAX: summary.max,
        ClaimKind.REGION_MEAN: summary.mean,
        ClaimKind.MISSING_HOURS: float(summary.missing_hours),
    }.get(req.kind)
    if req.kind is ClaimKind.HOURS_ABOVE:
        assert req.threshold is not None
        value = float(hours_above(data, window, req.region, req.threshold))
        fields["threshold"] = req.threshold
    return Claim.model_validate({**fields, "region": req.region, "value": value})


def scripted_arm(task: EvalTask, workspace: Workspace) -> ArmOutcome:
    """A fixed Python script per requirement. It cannot read the question text."""
    claims = [_scripted_claim(req, workspace) for req in task.requirements]
    final = workspace.verifier.verify_all(claims)
    return ArmOutcome(final, 0, 0.0, {"claims": len(claims)})

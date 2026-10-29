"""Approval gate and size-capped writing for every download.

A download runs only when a recorded human approval covers the action, the case, the
asset and the expected size at the current time. The writer then enforces the approved
byte cap on the actual stream and deletes a partial file that crosses it.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import yaml

from earthlab.cases.models import ApprovalAction, HumanApproval, RequestScope
from earthlab.digest import file_digest
from earthlab.trace import RunTrace

GATE_ACTOR = "approval_gate"


class ApprovalRefused(PermissionError):
    """No recorded approval covers this action; nothing was done."""


class CapExceeded(RuntimeError):
    """The stream crossed the approved byte cap; the partial file was deleted."""


def load_approvals(folder: Path) -> list[HumanApproval]:
    approvals: list[HumanApproval] = []
    for path in sorted(folder.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        approvals += [HumanApproval.model_validate(item) for item in raw.get("approvals", [])]
    return approvals


def authorize(
    approvals: list[HumanApproval],
    action: ApprovalAction,
    case_id: str,
    *,
    asset_id: str | None = None,
    request_bytes: int | None = None,
    request: RequestScope | None = None,
    at: datetime | None = None,
    trace: RunTrace | None = None,
) -> HumanApproval:
    """Return the approval that covers the request, or raise with every refusal reason.

    With a trace, the gate records `approval_requested` before the check and
    `approval_resolved` after it, so a run shows each consequential action it asked for.
    """
    moment = at or datetime.now(UTC)
    target = asset_id or case_id
    if trace is not None:
        trace.append(
            "approval_requested",
            GATE_ACTOR,
            action=action.value,
            case_id=case_id,
            asset_id=asset_id,
            request_bytes=request_bytes,
        )
    reasons: list[str] = []
    for approval in approvals:
        if approval.case_id != case_id:
            continue
        refusal = approval.refusal(
            action, moment, asset_id=asset_id, request_bytes=request_bytes, request=request
        )
        if refusal is None:
            _resolved(trace, action, target, approval.approval_id, None)
            return approval
        reasons.append(f"{approval.approval_id}: {refusal}")
    detail = "; ".join(reasons) or "no approval recorded for this case"
    _resolved(trace, action, target, None, detail)
    raise ApprovalRefused(f"{action.value} for {target} refused: {detail}")


def _resolved(
    trace: RunTrace | None,
    action: ApprovalAction,
    target: str,
    approval_id: str | None,
    refusal: str | None,
) -> None:
    if trace is not None:
        trace.append(
            "approval_resolved",
            GATE_ACTOR,
            action=action.value,
            target=target,
            approved=refusal is None,
            approval_id=approval_id,
            refusal=refusal,
        )


def write_capped(chunks: Iterable[bytes], path: Path, max_bytes: int) -> tuple[str, int]:
    """Write the stream to path; return (sha256, bytes). Over the cap: delete and raise."""
    tmp = path.with_suffix(path.suffix + ".part")
    written = 0
    try:
        with tmp.open("wb") as out:
            for chunk in chunks:
                written += len(chunk)
                if written > max_bytes:
                    raise CapExceeded(f"{path.name}: stream passed the {max_bytes}-byte cap")
                out.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(path)
    return file_digest(path), written

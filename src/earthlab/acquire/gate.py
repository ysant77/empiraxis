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
) -> HumanApproval:
    """Return the approval that covers the request, or raise with every refusal reason."""
    moment = at or datetime.now(UTC)
    reasons: list[str] = []
    for approval in approvals:
        if approval.case_id != case_id:
            continue
        refusal = approval.refusal(
            action, moment, asset_id=asset_id, request_bytes=request_bytes, request=request
        )
        if refusal is None:
            return approval
        reasons.append(f"{approval.approval_id}: {refusal}")
    detail = "; ".join(reasons) or "no approval recorded for this case"
    raise ApprovalRefused(f"{action.value} for {asset_id or case_id} refused: {detail}")


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

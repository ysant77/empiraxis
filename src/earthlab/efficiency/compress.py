"""Compact typed forms of PM briefs and worker evidence, with explicit references.

Scientific fields stay inline and typed: route, case, intent, period, value, unit,
availability time, verification status and approval state. Only free text (the question,
each constraint, each statement) moves behind a hash reference, so a repeated constraint is
stored once. Decoding rebuilds the original record and checks it against its hash. Nothing
here summarises text: a reference resolves to the exact original or raises.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import AwareDatetime, Field

from earthlab.contracts import Strict
from earthlab.efficiency.artifacts import (
    SHA256,
    ArtifactIntegrityError,
    ArtifactRef,
    ArtifactStore,
    canonical,
    model_digest,
)
from earthlab.planning.vocab import ResearchIntent
from earthlab.workflow.contracts import BriefProposal, ProductBriefV1, Route

Verification = Literal["verified", "unverified", "contradicted"]
Approval = Literal["not_required", "pending", "approved", "denied"]


class CompactBriefV1(Strict):
    schema_version: Literal["1"] = "1"
    task_id: str
    route: Route
    case_id: str | None
    intent: ResearchIntent
    target_quantity: str | None
    period_start: AwareDatetime | None
    period_end: AwareDatetime | None
    question: ArtifactRef
    constraints: tuple[ArtifactRef, ...]
    clarifications: tuple[ArtifactRef, ...]
    provenance: ArtifactRef  # request hash, topology and author of the original brief
    source_sha256: str = Field(pattern=SHA256)


class _Provenance(Strict):
    request_sha256: str
    topology: str
    author: dict[str, str | None]


def encode_brief(brief: ProductBriefV1, store: ArtifactStore) -> CompactBriefV1:
    b = brief.brief
    prov = _Provenance(
        request_sha256=brief.request_sha256,
        topology=brief.topology,
        author={k: v for k, v in brief.author.model_dump().items()},
    )
    return CompactBriefV1(
        task_id=brief.task_id,
        route=b.route,
        case_id=b.case_id,
        intent=b.intent,
        target_quantity=b.target_quantity,
        period_start=b.period_start,
        period_end=b.period_end,
        question=store.put_text(b.normalized_question),
        constraints=tuple(store.put_text(c) for c in b.constraints),
        clarifications=tuple(store.put_text(c) for c in b.clarifications_needed),
        provenance=store.put_record(prov),
        source_sha256=model_digest(brief),
    )


def decode_brief(compact: CompactBriefV1, store: ArtifactStore) -> ProductBriefV1:
    """Rebuild the original brief. Raises on a missing artifact or a hash mismatch."""
    prov = _Provenance.model_validate(store.get(compact.provenance))
    brief = ProductBriefV1.model_validate(
        {
            "task_id": compact.task_id,
            "request_sha256": prov.request_sha256,
            "topology": prov.topology,
            "author": prov.author,
            "brief": BriefProposal(
                route=compact.route,
                case_id=compact.case_id,
                normalized_question=store.text(compact.question),
                intent=compact.intent,
                target_quantity=compact.target_quantity,
                period_start=compact.period_start,
                period_end=compact.period_end,
                constraints=tuple(store.text(r) for r in compact.constraints),
                clarifications_needed=tuple(store.text(r) for r in compact.clarifications),
            ).model_dump(),
        }
    )
    if model_digest(brief) != compact.source_sha256:
        raise ArtifactIntegrityError("decoded brief does not match its source hash")
    return brief


class EvidenceRecord(Strict):
    """One worker finding with every field a reader needs to trust or reject it."""

    finding_id: str = Field(pattern=r"^[A-Z]+\d+\.\d+$")
    quantity: str
    value: float | None
    unit: str
    statement: str
    constraints: tuple[str, ...]
    available_at: AwareDatetime
    verification_status: Verification
    approval_state: Approval
    source_sha256s: tuple[str, ...] = ()


class CompactEvidenceRow(Strict):
    finding_id: str
    quantity: str
    value: float | None
    unit: str
    available_at: AwareDatetime
    verification_status: Verification
    approval_state: Approval
    source_sha256s: tuple[str, ...]
    statement: ArtifactRef
    constraints: tuple[ArtifactRef, ...]


class CompactEvidenceV1(Strict):
    schema_version: Literal["1"] = "1"
    task_id: str
    rows: tuple[CompactEvidenceRow, ...]
    source_sha256: str = Field(pattern=SHA256)


def _records_digest(records: tuple[EvidenceRecord, ...]) -> str:
    return hashlib.sha256(canonical([r.model_dump(mode="json") for r in records])).hexdigest()


def encode_evidence(
    task_id: str, records: tuple[EvidenceRecord, ...], store: ArtifactStore
) -> CompactEvidenceV1:
    rows = tuple(
        CompactEvidenceRow(
            finding_id=r.finding_id,
            quantity=r.quantity,
            value=r.value,
            unit=r.unit,
            available_at=r.available_at,
            verification_status=r.verification_status,
            approval_state=r.approval_state,
            source_sha256s=r.source_sha256s,
            statement=store.put_text(r.statement),
            constraints=tuple(store.put_text(c) for c in r.constraints),
        )
        for r in records
    )
    return CompactEvidenceV1(task_id=task_id, rows=rows, source_sha256=_records_digest(records))


def decode_evidence(compact: CompactEvidenceV1, store: ArtifactStore) -> tuple[EvidenceRecord, ...]:
    records = tuple(
        EvidenceRecord(
            finding_id=r.finding_id,
            quantity=r.quantity,
            value=r.value,
            unit=r.unit,
            statement=store.text(r.statement),
            constraints=tuple(store.text(c) for c in r.constraints),
            available_at=r.available_at,
            verification_status=r.verification_status,
            approval_state=r.approval_state,
            source_sha256s=r.source_sha256s,
        )
        for r in compact.rows
    )
    if _records_digest(records) != compact.source_sha256:
        raise ArtifactIntegrityError("decoded evidence does not match its source hash")
    return records


def inline_chars(model: Strict) -> int:
    """Size of a record as canonical JSON, in characters. A measure, not a token count."""
    return len(canonical(model.model_dump(mode="json")))

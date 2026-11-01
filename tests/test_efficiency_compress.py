from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from earthlab.efficiency.artifacts import (
    ArtifactIntegrityError,
    ArtifactRef,
    ArtifactStore,
    MissingArtifactError,
)
from earthlab.efficiency.compress import (
    EvidenceRecord,
    decode_brief,
    decode_evidence,
    encode_brief,
    encode_evidence,
    inline_chars,
)
from earthlab.workflow.contracts import BriefProposal, ProductBriefV1, RoleCall

H = "a" * 64
T0 = datetime(2015, 9, 1, tzinfo=UTC)


def _brief(
    constraints: tuple[str, ...] = ("keep the whole month", "end excluded"),
) -> ProductBriefV1:
    return ProductBriefV1(
        task_id="t1",
        request_sha256=H,
        topology="separate",
        brief=BriefProposal(
            route="engineer",
            case_id="kalimantan-2015-burned-area",
            normalized_question="How much area burned in September 2015?",
            intent="observational_summary",
            target_quantity="burned_area",
            period_start=T0,
            period_end=datetime(2015, 10, 1, tzinfo=UTC),
            constraints=constraints,
            clarifications_needed=(),
        ),
        author=RoleCall(
            role_id="product_manager", provider="p", model="m", logical_model="l", served_model="s"
        ),
    )


def _record(**over: Any) -> EvidenceRecord:
    base: dict[str, Any] = {
        "finding_id": "A1.1",
        "quantity": "burned_area_ha",
        "value": 77426.0,
        "unit": "ha",
        "statement": "Mapped burned area for the month.",
        "constraints": ("valid fraction >= 0.8",),
        "available_at": T0,
        "verification_status": "verified",
        "approval_state": "not_required",
        "source_sha256s": (H,),
    }
    return EvidenceRecord.model_validate(base | over)


def test_brief_round_trip_is_exact() -> None:
    store, brief = ArtifactStore(), _brief()
    compact = encode_brief(brief, store)
    assert decode_brief(compact, store) == brief
    assert compact.period_start == T0 and compact.intent == brief.brief.intent


def test_brief_constraints_are_kept_and_deduplicated() -> None:
    store = ArtifactStore()
    a = encode_brief(_brief(), store)
    b = encode_brief(_brief(("end excluded",)), store)
    assert a.constraints[1] == b.constraints[0]
    assert [store.text(r) for r in a.constraints] == ["keep the whole month", "end excluded"]


def test_brief_decode_fails_on_missing_artifact() -> None:
    store, other = ArtifactStore(), ArtifactStore()
    compact = encode_brief(_brief(), store)
    with pytest.raises(MissingArtifactError):
        decode_brief(compact, other)


def test_brief_decode_fails_on_tampered_hash() -> None:
    store = ArtifactStore()
    compact = encode_brief(_brief(), store)
    bad = compact.model_copy(update={"source_sha256": "b" * 64})
    with pytest.raises(ArtifactIntegrityError):
        decode_brief(bad, store)


def test_evidence_round_trip_keeps_every_critical_field() -> None:
    store = ArtifactStore()
    records = (
        _record(),
        _record(
            finding_id="A1.2",
            value=None,
            verification_status="unverified",
            approval_state="pending",
            unit="fraction",
        ),
    )
    compact = encode_evidence("t1", records, store)
    assert decode_evidence(compact, store) == records
    row = compact.rows[1]
    assert (row.verification_status, row.approval_state, row.available_at) == (
        "unverified",
        "pending",
        T0,
    )


def test_evidence_decode_fails_on_missing_reference() -> None:
    store = ArtifactStore()
    compact = encode_evidence("t1", (_record(),), store)
    with pytest.raises(MissingArtifactError):
        decode_evidence(compact, ArtifactStore())


def test_evidence_decode_fails_when_a_row_changes() -> None:
    store = ArtifactStore()
    compact = encode_evidence("t1", (_record(),), store)
    row = compact.rows[0].model_copy(update={"verification_status": "unverified"})
    forged = compact.model_copy(update={"rows": (row,)})
    with pytest.raises(ArtifactIntegrityError):
        decode_evidence(forged, store)


def test_schema_validation_rejects_lossy_forms() -> None:
    with pytest.raises(ValueError):
        _record(available_at=datetime(2015, 9, 1))  # naive time: availability would be lost
    with pytest.raises(ValueError):
        _record(verification_status="probably")
    with pytest.raises(ValueError):
        ArtifactRef(kind="text", sha256="xyz")
    with pytest.raises(ValueError):
        EvidenceRecord.model_validate({"finding_id": "A1.1"})


def test_store_is_write_once_and_checks_integrity() -> None:
    store = ArtifactStore()
    ref = store.put_text("same")
    assert store.put_text("same") == ref
    store._items[ref.sha256] = b'"changed"'
    with pytest.raises(ArtifactIntegrityError):
        store.get(ref)
    rec = store.put_record(_record())
    assert rec.kind == "record"
    with pytest.raises(ArtifactIntegrityError):
        store.text(rec)


def test_inline_size_is_a_measure_only() -> None:
    store = ArtifactStore()
    compact = encode_brief(_brief(), store)
    assert inline_chars(compact) > 0 and inline_chars(_brief()) > 0

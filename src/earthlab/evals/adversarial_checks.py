"""Adapters from one adversarial case to one existing deterministic check.

Each adapter calls production code and returns (refused, evidence). An adapter adds no rule of
its own, except where it compares a claimed number with the value that production code computes.
No adapter calls a model or the network.
"""

from __future__ import annotations

import os
import secrets
import shutil
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from earthlab.agent.findings import FindingsLedger
from earthlab.events.manifest import ManifestError, verified_run
from earthlab.forecast.dataset import parse_label
from earthlab.harness import gates
from earthlab.harness import review_contracts as rules
from earthlab.harness.contracts import MethodProposalV1
from earthlab.haze.transport_checks import check_precip, rate_mm_h, wind_sign_error
from earthlab.haze.wind import angular_difference, uv_from_wind, wind_from_uv
from earthlab.mlops.contracts import Span
from earthlab.mlops.encoder import CHANNELS, EncoderManifestV1, ReuseRefused, check_reuse
from earthlab.runtime import build_registry, open_workspace
from earthlab.safety.scope import answer_out_of_scope, question_out_of_scope
from earthlab.team import resources as res
from earthlab.verify.claims import Claim, Verdict
from earthlab.verify.language import language_violation
from earthlab.verify.recompute import _cell

from .adversarial_facts import FACTS, LEAD_CASE, decision_findings, plan, profile_with

Outcome = tuple[bool, str]
SHA = "a" * 64


def scope_question(question: str) -> Outcome:
    why = question_out_of_scope(question)
    return why is not None, why or "in scope"


def scope_answer(answer: str) -> Outcome:
    why = answer_out_of_scope(answer)
    return why is not None, why or "in scope"


def claim_language(statement: str) -> Outcome:
    why = language_violation(statement)
    return why is not None, why or "allowed wording"


def nea_cell(text: str) -> Outcome:
    value = _cell(text)
    return value is None, "cell dropped" if value is None else f"read as {value}"


def nea_label(text: str) -> Outcome:
    moment = parse_label(text)
    return moment is None, "label refused" if moment is None else f"read as {moment}"


def verify_claim(data_dir: Path, **claim: Any) -> Outcome:
    verifier = open_workspace(data_dir).verifier
    result = verifier.verify(Claim.model_validate({"statement": "Checked value.", **claim}))
    return result.verdict != Verdict.SUPPORTED, f"{result.verdict.value}: {result.reason}"


def tool_call(data_dir: Path, name: str, arguments: str) -> Outcome:
    result = build_registry(open_workspace(data_dir), FindingsLedger()).execute(name, arguments)
    return result.outcome.value != "executed", f"{result.outcome.value}: {result.error or 'ran'}"


def contract_extra(field: str, value: Any) -> Outcome:
    try:
        MethodProposalV1.model_validate({**LEAD_CASE, field: value})
    except ValidationError as exc:
        return True, exc.errors()[0]["msg"]
    return False, "accepted"


def proposal_text(field: str, text: str) -> Outcome:
    from earthlab.harness.method_review import check_proposal

    found = check_proposal(MethodProposalV1.model_validate({**LEAD_CASE, field: text}), FACTS)
    codes = sorted(f.code.value for f in found if f.blocking)
    return bool(codes), ", ".join(codes) or "no blocking finding"


def plan_latency(input_offset_hours: int, latency_hours: int) -> Outcome:
    found = gates.check_plan(plan(input_offset_hours), profile_with(latency_hours), ("ridge",), 1.0)
    leak = [r.detail for r in found if r.code == gates.Code.TEMPORAL_LEAKAGE]
    return bool(leak), leak[0] if leak else "inputs available at issue time"


def problem_data(variable: str, unit: str) -> Outcome:
    found = gates.check_problem(FACTS.problem, profile_with(0, variable=variable, unit=unit))
    return bool(found), "; ".join(f"{r.code}: {r.detail}" for r in found) or "fits"


def segmentation(bands: list[str], resolution_m: float, label_provenance: str) -> Outcome:
    profile = profile_with(0, bands=tuple(bands), resolution_m=resolution_m,
                           label_provenance=label_provenance)  # fmt: skip
    found = gates.check_segmentation(profile)
    return bool(found), "; ".join(f"{r.code}: {r.detail}" for r in found) or "fits"


def wind_sign(u_ms: float, v_ms: float, claimed_from_deg: float) -> Outcome:
    wrong = wind_sign_error(u_ms, v_ms, claimed_from_deg)
    return wrong, f"true wind-from {wind_from_uv(u_ms, v_ms).from_deg}"


def bearing_mean(bearings: list[float], claimed_mean_deg: float) -> Outcome:
    parts = [uv_from_wind(1.0, b) for b in bearings]
    u = sum(p[0] for p in parts) / len(parts)
    v = sum(p[1] for p in parts) / len(parts)
    mean = wind_from_uv(u, v, calm_ms=0.0).from_deg
    off = mean is None or angular_difference(claimed_mean_deg, mean) > 5.0
    return off, f"vector mean {mean}"


def precip(values_mm: list[float], unit: str = "mm") -> Outcome:
    found = check_precip(values_mm, "m" if unit == "m" else "mm")
    return bool(found.issues), "; ".join(found.issues) or "plausible hourly rain"


def rain_rate(total_mm: float, hours: float, claimed_mm_h: float) -> Outcome:
    rate = rate_mm_h(total_mm, hours)
    return abs(rate - claimed_mm_h) > 1e-6, f"rate {rate:g} mm/h"


def _request(request_id: str, expires: datetime) -> res.ResourceRequestV1:
    return res.ResourceRequestV1(
        request_id=request_id, parent_task_id="adversarial.suite", purpose="One small test file.",
        asset="test asset", url="https://example.org/file.bin", max_bytes=1000,
        content_types=("application/octet-stream",), license_terms="CC-BY-4.0",
        expires_utc=expires, scientific_need="A test of the approval gate.", risk="none",
    )  # fmt: skip


def _endorsed(desk: res.ResourceDesk, request_id: str, expires: datetime) -> None:
    desk.open(_request(request_id, expires))
    desk.review(request_id, "geospatial_engineer", "test", True, "Fits the need.")
    desk.review(request_id, "product_manager", "test", True, "Fits the scope.")


def _forge(desk: res.ResourceDesk, request_id: str, key: str, variant: str) -> None:
    view = desk.view(request_id)
    other = view.request.sha256() if variant != "mismatched" else SHA
    approval = res.ResourceApprovalV1(
        request_id=request_id, request_sha256=other, approved=True, approver="owner",
        decided_at_utc=datetime.now(UTC),
    )  # fmt: skip
    signature = res.sign(approval, key) if variant == "mismatched" else "0" * 64
    path = desk.root / request_id / res.APPROVAL_FILE
    path.write_text(approval.model_copy(update={"signature": signature}).model_dump_json())
    desk._trace(request_id).append(
        "resource_decided", "human_director", approved=True, approver="owner", approval_sha256=SHA
    )


def approval(variant: str) -> Outcome:
    """A request with a test key: valid, wrong_key, forged, mismatched or expired."""
    key, saved = secrets.token_hex(16), os.environ.get(res.OPERATOR_KEY_ENV)
    os.environ[res.OPERATOR_KEY_ENV] = key
    try:
        with tempfile.TemporaryDirectory() as folder:
            desk = res.ResourceDesk(Path(folder))
            hours = -1 if variant == "expired" else 24
            _endorsed(desk, "req-1", datetime.now(UTC) + timedelta(hours=hours))
            if variant in ("forged", "mismatched"):
                _forge(desk, "req-1", key, variant)
            else:
                offered = key if variant != "wrong_key" else secrets.token_hex(16)
                desk.decide("req-1", True, offered, "owner")
            desk.authorized("req-1")
    except res.RequestRefused as exc:
        return True, str(exc)
    finally:
        os.environ.pop(res.OPERATOR_KEY_ENV)
        if saved is not None:
            os.environ[res.OPERATOR_KEY_ENV] = saved
    return False, "authorized"


def replay_altered(replay_root: Path, run: str, mutation: str) -> Outcome:
    """Copy the published replays, change one file of one run, and check that run."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / "replay"
        shutil.copytree(replay_root, root)
        target = root / run / "result.json"
        if mutation == "edit":
            target.write_text(target.read_text().replace('"', "'", 1))
        elif mutation == "delete":
            target.unlink()
        try:
            verified_run(root, run)
        except ManifestError as exc:
            return True, str(exc)
    return False, "manifest matches"


def encoder_reuse(selection: list[int], scored: list[int], train_last: int = 41662) -> Outcome:
    manifest = EncoderManifestV1(
        architecture="gru", hidden=16, layers=1, inputs=15, window=48, offset=2,
        channels=CHANNELS, preprocessing_sha256=SHA, source_sha256=SHA, weights_sha256=SHA,
        model_sha256=SHA, code_revision="adversarial-suite",
        train_span=Span(first=0, last=train_last),
        selection_span=Span(first=selection[0], last=selection[1]),
    )  # fmt: skip
    try:
        check_reuse(manifest, architecture="gru", preprocessing_sha256=SHA, source_sha256=SHA,
                    train_end=train_last, scored=Span(first=scored[0], last=scored[1]))  # fmt: skip
    except ReuseRefused as exc:
        return True, str(exc)
    return False, "reuse allowed"


def sealed(claim: str, samples: str, problem_id: str = "pm25-regression-6h") -> Outcome:
    found = rules.sealed_issues(claim, problem_id, samples)
    return bool(found), "; ".join(found) or "open period"


def criteria(change: dict[str, Any]) -> Outcome:
    original = MethodProposalV1.model_validate(LEAD_CASE)
    found = rules.drift_issues(MethodProposalV1.model_validate({**LEAD_CASE, **change}), original)
    return bool(found), "; ".join(found) or "measure unchanged"


def subgroup(outcome: str, limitations: list[str]) -> Outcome:
    """Refused means the failure cannot stay hidden: code writes it into the limitations."""
    added = decision_findings(outcome, limitations)
    return bool(added), "; ".join(added) or "nothing added"


CHECKS: dict[str, Callable[..., Outcome]] = {
    "scope_question": scope_question, "scope_answer": scope_answer,
    "claim_language": claim_language, "nea_cell": nea_cell, "nea_label": nea_label,
    "verify_claim": verify_claim, "tool_call": tool_call, "contract_extra": contract_extra,
    "proposal_text": proposal_text, "plan_latency": plan_latency, "problem_data": problem_data,
    "segmentation": segmentation, "wind_sign": wind_sign, "bearing_mean": bearing_mean,
    "precip": precip, "rain_rate": rain_rate, "approval": approval,
    "replay_altered": replay_altered, "encoder_reuse": encoder_reuse, "sealed": sealed,
    "criteria": criteria, "subgroup": subgroup,
}  # fmt: skip
NEEDS_DATA = {"verify_claim", "tool_call"}
NEEDS_REPLAY = {"replay_altered"}

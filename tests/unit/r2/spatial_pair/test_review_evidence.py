"""Exact frame review bodies preserve role and byte identity."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from lib.db.models.spatial_pair import SpatialPairDecisionModel, SpatialPairV2CustodyModel
from lib.db.repositories.spatial_pair import SpatialPairIntegrityError
from lib.db.repositories.spatial_pair_v2 import verify_stored_pair_decision_v2, verify_stored_pair_decision_versioned
from r2.contracts.review_evidence import ReviewEvidenceV1, ReviewSnapshotV1
from r2.contracts.spatial_pair import PairDecisionCommandV2, PairDecisionResultV2, PairDecisionV2
from r2.spatial_pair.digests import (
    pair_authorization_digest,
    pair_command_digest,
    pair_command_digest_v2,
    pair_decision_digest_v2,
    pair_result_digest_v2,
    scoped_pair_id,
)
from r2.spatial_pair.review_digests import (
    ReviewEvidenceIntegrityError,
    review_evidence_digest,
    review_snapshot_digest,
    verify_stored_review_evidence,
)


def _snapshot() -> dict[str, Any]:
    from json import loads

    fixture = Path(__file__).resolve().parents[3] / "fixtures/r2/m8c_location_binding_v1_vectors.json"
    cases = {case["name"]: case for case in loads(fixture.read_text())["cases"]}
    envelope = cases["binding_envelope"]["body"]
    claims = envelope["ordered_claims"]
    return {
        "session_id": "a" * 32,
        "user_id": "u1",
        "project_name": "demo",
        "principal": "human:reviewer-1",
        "scene_ref": envelope["scene_ref"],
        "target_ref": envelope["target_ref"],
        "binding_id": envelope["binding_id"],
        "binding_version": 1,
        "envelope_digest": cases["binding_envelope"]["digest"],
        "core_digest": cases["binding_core"]["digest"],
        "frames": [
            {
                "role": "MASTER",
                "receipt_id": claims[0]["receipt_id"],
                "receipt_digest": claims[0]["receipt_digest"],
                "png_digest": "sha256:" + "1" * 64,
            },
            {
                "role": "REVERSE",
                "receipt_id": claims[1]["receipt_id"],
                "receipt_digest": claims[1]["receipt_digest"],
                "png_digest": "sha256:" + "2" * 64,
            },
        ],
        "created_at": "2026-10-06T00:00:00Z",
        "expires_at": "2026-10-06T00:10:00Z",
    }


def _evidence(snapshot: ReviewSnapshotV1) -> dict[str, Any]:
    frames = snapshot.frames
    return {
        "snapshot": snapshot.model_dump(mode="json"),
        "snapshot_digest": review_snapshot_digest(snapshot.model_dump(mode="json")),
        "deliveries": [
            {
                "attempt_id": "attempt-1",
                "role": "MASTER",
                "png_digest": frames[0].png_digest,
                "delivered_at": "2026-10-06T00:01:00Z",
            },
            {
                "attempt_id": "attempt-2",
                "role": "REVERSE",
                "png_digest": frames[1].png_digest,
                "delivered_at": "2026-10-06T00:02:00Z",
            },
        ],
        "acknowledgments": [
            {
                "principal": snapshot.principal,
                "role": "MASTER",
                "png_digest": frames[0].png_digest,
                "decoded": True,
                "delivery_attempt_id": "attempt-1",
                "acknowledged_at": "2026-10-06T00:03:00Z",
            },
            {
                "principal": snapshot.principal,
                "role": "REVERSE",
                "png_digest": frames[1].png_digest,
                "decoded": True,
                "delivery_attempt_id": "attempt-2",
                "acknowledged_at": "2026-10-06T00:04:00Z",
            },
        ],
    }


def test_review_evidence_binds_two_ordered_frames_and_deliveries() -> None:
    snapshot = ReviewSnapshotV1.model_validate(_snapshot())
    evidence = ReviewEvidenceV1.model_validate(_evidence(snapshot))
    assert review_evidence_digest(evidence.model_dump(mode="json")).startswith("sha256:")
    changed = snapshot.model_copy(update={"principal": "human:other"})
    assert review_snapshot_digest(changed.model_dump(mode="json")) != evidence.snapshot_digest


def test_review_snapshot_rejects_role_swap_and_long_lifetime() -> None:
    base = _snapshot()
    for changed in (
        {"frames": list(reversed(base["frames"]))},
        {"expires_at": "2026-10-06T00:10:01Z"},
        {"session_id": "weak"},
    ):
        with pytest.raises(ValidationError):
            ReviewSnapshotV1.model_validate(base | changed)


def test_review_evidence_rejects_missing_or_mismatched_acknowledgment() -> None:
    snapshot = ReviewSnapshotV1.model_validate(_snapshot())
    base = _evidence(snapshot)
    acks = base["acknowledgments"]
    assert isinstance(acks, list)
    for changed in (
        {"acknowledgments": acks[:1]},
        {"acknowledgments": [acks[0], acks[0]]},
        {"acknowledgments": [acks[0], acks[1] | {"decoded": False}]},
        {"acknowledgments": [acks[0], acks[1] | {"delivery_attempt_id": "attempt-1"}]},
        {"acknowledgments": [acks[0], acks[1] | {"png_digest": snapshot.frames[0].png_digest}]},
        {"acknowledgments": [acks[0], acks[1] | {"principal": "human:other"}]},
        {"snapshot_digest": "sha256:" + "0" * 64},
    ):
        with pytest.raises((ValidationError, ValueError)):
            review_evidence_digest(base | changed)


def test_review_evidence_rejects_ack_before_delivery_or_after_expiry() -> None:
    snapshot = ReviewSnapshotV1.model_validate(_snapshot())
    base = _evidence(snapshot)
    acks = base["acknowledgments"]
    assert isinstance(acks, list)
    for time in ("2026-10-06T00:01:59Z", "2026-10-06T00:10:01Z"):
        with pytest.raises((ValidationError, ValueError)):
            ReviewEvidenceV1.model_validate(base | {"acknowledgments": [acks[0], acks[1] | {"acknowledged_at": time}]})


def test_snapshot_digest_changes_with_png_bytes() -> None:
    snapshot = ReviewSnapshotV1.model_validate(_snapshot())
    before = review_snapshot_digest(snapshot.model_dump(mode="json"))
    frames = snapshot.model_dump(mode="json")["frames"]
    frames[0]["png_digest"] = "sha256:" + "f" * 64
    changed = ReviewSnapshotV1.model_validate(snapshot.model_dump(mode="json") | {"frames": frames})
    assert review_snapshot_digest(changed.model_dump(mode="json")) != before


def test_pair_v2_command_binds_review_reference_without_changing_v1_digest() -> None:
    from json import loads

    fixture = Path(__file__).resolve().parents[3] / "fixtures/r2/m8c_pair_contract_vectors.json"
    cases = {case["name"]: case for case in loads(fixture.read_text())["cases"]}
    v1 = cases["pair_command_approve"]["body"]
    assert pair_command_digest(v1) == cases["pair_command_approve"]["digest"]
    reviewed = PairDecisionCommandV2.model_validate(
        v1 | {"review_session_id": "a" * 32, "review_evidence_digest": "sha256:" + "1" * 64}
    )
    digest = pair_command_digest_v2(reviewed.model_dump(mode="json"))
    assert digest == "sha256:49f5c762c45b8ee2755fa01bd7a3c1de6cb2755d486a10a1a1f90508a63895fd"
    changed = reviewed.model_dump(mode="json") | {"review_evidence_digest": "sha256:" + "2" * 64}
    assert digest != pair_command_digest_v2(changed)
    assert pair_command_digest(v1) == cases["pair_command_approve"]["digest"]
    with pytest.raises(ValidationError):
        PairDecisionCommandV2.model_validate(v1)


def test_stored_review_evidence_recomputes_digest_and_checks_scope() -> None:
    snapshot = ReviewSnapshotV1.model_validate(_snapshot())
    body = _evidence(snapshot)
    digest = review_evidence_digest(body)
    verified = verify_stored_review_evidence(
        body,
        expected_digest=digest,
        user_id="u1",
        project_name="demo",
        principal="human:reviewer-1",
        session_id="a" * 32,
    )
    assert verified.snapshot.session_id == "a" * 32

    changed = _evidence(snapshot)
    acknowledgments = changed["acknowledgments"]
    assert isinstance(acknowledgments, list)
    acknowledgments[0] = acknowledgments[0] | {"acknowledged_at": "2026-10-06T00:05:00Z"}
    for stored_body, scope in (
        (changed, {}),
        (body, {"project_name": "foreign"}),
        (body, {"session_id": "b" * 32}),
    ):
        expected = {
            "expected_digest": digest,
            "user_id": "u1",
            "project_name": "demo",
            "principal": "human:reviewer-1",
            "session_id": "a" * 32,
        } | scope
        with pytest.raises(ReviewEvidenceIntegrityError):
            verify_stored_review_evidence(stored_body, **expected)


def test_v2_decision_envelope_binds_exact_command_authorization_and_review_evidence() -> None:
    from json import loads

    fixture = Path(__file__).resolve().parents[3] / "fixtures/r2/m8c_pair_contract_vectors.json"
    cases = {case["name"]: case for case in loads(fixture.read_text())["cases"]}
    snapshot = ReviewSnapshotV1.model_validate(_snapshot())
    evidence = ReviewEvidenceV1.model_validate(_evidence(snapshot))
    evidence_digest = review_evidence_digest(evidence.model_dump(mode="json"))
    command_body = cases["pair_command_approve"]["body"] | {
        "user_id": snapshot.user_id,
        "project_name": snapshot.project_name,
        "principal": snapshot.principal,
        "expected_scene_ref": snapshot.scene_ref.model_dump(mode="json"),
        "expected_target_ref": snapshot.target_ref.model_dump(mode="json"),
        "binding_id": snapshot.binding_id,
        "expected_binding_version": snapshot.binding_version,
        "expected_envelope_digest": snapshot.envelope_digest,
        "expected_core_digest": snapshot.core_digest,
        "views": [
            {"role": frame.role, "receipt_id": frame.receipt_id, "receipt_digest": frame.receipt_digest}
            for frame in snapshot.frames
        ],
        "review_session_id": snapshot.session_id,
        "review_evidence_digest": evidence_digest,
    }
    command = PairDecisionCommandV2.model_validate(command_body)
    authorization = {
        "user_id": command.user_id,
        "project_name": command.project_name,
        "authenticated_principal": command.principal,
        "authority_role": "HUMAN_SHOWRUNNER",
        "command_digest": pair_command_digest_v2(command.model_dump(mode="json")),
        "authorization_ref": "signed-grant-event-1",
        "authenticated_at": "2026-10-06T00:04:30Z",
    }
    body = {
        "decision_schema": "r2.m8.spatial.pair.decision.v2",
        "command": command.model_dump(mode="json"),
        "command_digest": authorization["command_digest"],
        "pair_id": scoped_pair_id(
            user_id=command.user_id, project_name=command.project_name, binding_id=command.binding_id
        ),
        "pair_version": 1,
        "reviewer_id": command.principal,
        "authorization": authorization,
        "authorization_digest": pair_authorization_digest(authorization),
        "review_evidence": evidence.model_dump(mode="json"),
        "decided_at": "2026-10-06T00:05:00Z",
    }
    decision = PairDecisionV2.model_validate(body)
    digest = pair_decision_digest_v2(decision.model_dump(mode="json"))
    assert digest == "sha256:8e16fad34c405ea4ae757e990194b7d2be8cb1993615ff821a4215929b353153"
    assert pair_decision_digest_v2(decision.model_dump(mode="json")) == digest
    for changed in (
        {"review_evidence": evidence.model_dump(mode="json") | {"snapshot_digest": "sha256:" + "f" * 64}},
        {"command": command.model_dump(mode="json") | {"review_evidence_digest": "sha256:" + "f" * 64}},
        {"reviewer_id": "human:other"},
    ):
        with pytest.raises((ValidationError, ValueError)):
            PairDecisionV2.model_validate(body | changed)
    result = PairDecisionResultV2(
        result_schema="r2.m8.spatial.pair.result.v2",
        command_digest=decision.command_digest,
        pair_id=decision.pair_id,
        pair_version=decision.pair_version,
        decision_digest=digest,
        decision=command.decision,
        binding_id=command.binding_id,
        binding_version=command.expected_binding_version,
        binding_envelope_digest=command.expected_envelope_digest,
        binding_core_digest=command.expected_core_digest,
        scene_ref=command.expected_scene_ref,
        target_ref=command.expected_target_ref,
        review_session_id=command.review_session_id,
        review_evidence_digest=command.review_evidence_digest,
    )
    assert pair_result_digest_v2(result.model_dump(mode="json")) == (
        "sha256:aaf5110d4b2041143937843d8498c2ceb666e3abc825ece6574c3524a8107d92"
    )

    row = SpatialPairDecisionModel(
        user_id=command.user_id,
        project_name=command.project_name,
        pair_id=decision.pair_id,
        pair_version=decision.pair_version,
        decision_body_json=decision.model_dump(mode="json"),
        decision_digest=digest,
        command_digest=decision.command_digest,
        authorization_digest=decision.authorization_digest,
        binding_id=command.binding_id,
        binding_version=command.expected_binding_version,
        binding_envelope_digest=command.expected_envelope_digest,
        binding_core_digest=command.expected_core_digest,
        target_type=command.expected_target_ref.target_type.value,
        target_id=command.expected_target_ref.target_id,
        target_registry_version=command.expected_target_ref.registry_version,
        target_version_digest=command.expected_target_ref.version_digest,
        scene_type=command.expected_scene_ref.target_type.value,
        scene_id=command.expected_scene_ref.target_id,
        scene_registry_version=command.expected_scene_ref.registry_version,
        scene_version_digest=command.expected_scene_ref.version_digest,
        master_receipt_id=command.views[0].receipt_id,
        reverse_receipt_id=command.views[1].receipt_id,
        decision=command.decision,
    )
    custody = SpatialPairV2CustodyModel(
        user_id=command.user_id,
        project_name=command.project_name,
        pair_id=decision.pair_id,
        pair_version=decision.pair_version,
        review_session_id=command.review_session_id,
        review_evidence_digest=command.review_evidence_digest,
        decision_digest=digest,
    )
    expected = {
        "user_id": command.user_id,
        "project_name": command.project_name,
        "binding_id": command.binding_id,
        "expected_binding_version": command.expected_binding_version,
        "expected_envelope_digest": command.expected_envelope_digest,
        "expected_core_digest": command.expected_core_digest,
        "expected_target_ref": command.expected_target_ref,
        "expected_scene_ref": command.expected_scene_ref,
    }
    assert verify_stored_pair_decision_v2(row, custody, **expected).decision_digest == digest
    assert verify_stored_pair_decision_versioned(row, custody, **expected).decision_digest == digest
    with pytest.raises(SpatialPairIntegrityError):
        verify_stored_pair_decision_v2(row, None, **expected)
    with pytest.raises(SpatialPairIntegrityError):
        verify_stored_pair_decision_versioned(row, None, **expected)
    for record, field, replacement in (
        (row, "decision_digest", "sha256:" + "0" * 64),
        (row, "master_receipt_id", "foreign-receipt"),
        (custody, "review_session_id", "b" * 32),
        (custody, "review_evidence_digest", "sha256:" + "0" * 64),
        (custody, "project_name", "foreign"),
    ):
        original = getattr(record, field)
        setattr(record, field, replacement)
        with pytest.raises(SpatialPairIntegrityError):
            verify_stored_pair_decision_v2(row, custody, **expected)
        setattr(record, field, original)

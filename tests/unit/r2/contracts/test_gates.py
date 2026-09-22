from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from r2.contracts.gates import (
    FinalCutReceipt,
    GateAuthorization,
    GreenlightDecision,
    PublishApprovalDecision,
)

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
NAIVE_NOW = datetime(2026, 9, 22, 12, 0)


def _authorization(**overrides: object) -> GateAuthorization:
    defaults: dict[str, object] = {
        "authenticated_principal": "operator-1",
        "authority_role": "HUMAN_OPERATOR",
        "authorized_at": NOW,
    }
    defaults.update(overrides)
    return GateAuthorization.model_validate(defaults)


def test_greenlight_decision_round_trips() -> None:
    decision = GreenlightDecision(
        decision_id="d-greenlight-1",
        user_id="u1",
        project_name="p1",
        source_digest="sha256:" + "a" * 64,
        action="GREENLIGHT",
        authorization=_authorization(),
        sequence=1,
        created_at=NOW,
    )
    assert GreenlightDecision.model_validate(decision.model_dump(mode="json")) == decision


def test_greenlight_decision_rejects_an_unknown_action() -> None:
    with pytest.raises(ValidationError):
        GreenlightDecision(
            decision_id="d-1",
            user_id="u1",
            project_name="p1",
            source_digest="sha256:" + "a" * 64,
            action="APPROVE",  # not a valid GreenlightDecision action
            authorization=_authorization(),
            sequence=1,
            created_at=NOW,
        )


def test_publish_approval_decision_round_trips() -> None:
    decision = PublishApprovalDecision(
        decision_id="d-publish-1",
        user_id="u1",
        project_name="p1",
        deliverable_digest="sha256:" + "b" * 64,
        platform="youtube",
        visibility="unlisted",
        action="APPROVE_PUBLISH",
        authorization=_authorization(),
        sequence=1,
        created_at=NOW,
    )
    assert PublishApprovalDecision.model_validate(decision.model_dump(mode="json")) == decision


def test_final_cut_receipt_round_trips() -> None:
    receipt = FinalCutReceipt(
        user_id="u1",
        project_name="p1",
        artifact_key="videos:1:SH01",
        selected_candidate_id="CAND-1",
        content_fingerprint="sha256:" + "c" * 64,
        approval_record="APR-SH01",
        selected_by="operator-1",
        selected_at=NOW,
        sequence=1,
    )
    assert FinalCutReceipt.model_validate(receipt.model_dump(mode="json")) == receipt


def test_gate_authorization_rejects_a_naive_timestamp() -> None:
    with pytest.raises(ValidationError):
        GateAuthorization(
            authenticated_principal="operator-1", authority_role="HUMAN_OPERATOR", authorized_at=NAIVE_NOW
        )


def test_final_cut_receipt_rejects_a_naive_selected_at() -> None:
    with pytest.raises(ValidationError):
        FinalCutReceipt(
            user_id="u1",
            project_name="p1",
            artifact_key="videos:1:SH01",
            selected_candidate_id="CAND-1",
            content_fingerprint="sha256:" + "c" * 64,
            approval_record="APR-SH01",
            selected_by="operator-1",
            selected_at=NAIVE_NOW,
            sequence=1,
        )


def test_gate_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        GateAuthorization.model_validate(
            {
                "authenticated_principal": "operator-1",
                "authority_role": "HUMAN_OPERATOR",
                "authorized_at": NOW,
                "unexpected_field": "nope",
            }
        )

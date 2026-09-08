"""D08/C02 — same-execution Retry Identity Guard."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.contracts import (
    ExecutionDecision,
    ExecutionIdentityStability,
    ExecutionType,
    Provenance,
    ProvenanceActor,
    ProviderRequest,
    RetryDisposition,
)
from r2.production_intelligence.execution import RetryIdentityGuard

_PROV = Provenance(created_by=ProvenanceActor.SYSTEM, created_at=datetime(2026, 9, 7, 12, 0, tzinfo=UTC))


def _decision(**over) -> ExecutionDecision:
    base = {
        "id": "ED:SH01:cap:a:abc",
        "target_ref": "SH01",
        "method_decision_ref": "MD:SH01",
        "prompt_plan_ref": "PP:SH01",
        "capability_resolution_ref": "req-hash",
        "adapter_id": "adapter:x",
        "provider_id": "provider-x",
        "model_or_tool_id": "cap:a",
        "execution_type": ExecutionType.API,
        "capability_descriptor_version": "cat-v1",
        "observation_snapshot_ref": "obs-1",
        "execution_identity_stability": ExecutionIdentityStability.IMMUTABLE_REVISION,
        "request_semantics_hash": "r" * 16,
        "selection_policy_version": "sel-v1",
        "provenance": _PROV,
    }
    base.update(over)
    return ExecutionDecision(**base)


def _request(**over) -> ProviderRequest:
    base = {
        "id": "REQ-1",
        "method_decision_ref": "MD:SH01",
        "prompt_plan_ref": "PP:SH01",
        "provider": "provider-x",
        "model": "cap:a",
        "endpoint": "generate/api",
        "payload": {"instruction": "Maya reacts"},
        "adapter_version": "cat-v1",
    }
    base.update(over)
    return ProviderRequest(**base)


def _evaluate(prior_d, cur_d, prior_r, cur_r, *, ambiguous=False, idempotent=False):
    return RetryIdentityGuard().evaluate(
        prior_decision=prior_d,
        current_decision=cur_d,
        prior_request=prior_r,
        current_request=cur_r,
        previous_attempt_side_effect_ambiguous=ambiguous,
        provider_idempotency_supported=idempotent,
    )


def test_identical_decision_and_request_allows_same_execution_retry() -> None:
    result = _evaluate(_decision(), _decision(), _request(), _request())
    assert result.allowed is True
    assert result.disposition is RetryDisposition.RETRY_SAME_EXECUTION
    assert result.reason_codes == ()


def test_provider_change_forbids_same_execution_retry() -> None:
    result = _evaluate(_decision(), _decision(provider_id="provider-y"), _request(), _request(provider="provider-y"))
    assert result.allowed is False
    assert result.disposition is RetryDisposition.NEW_EXECUTION_DECISION_REQUIRED
    assert "PROVIDER_MISMATCH" in result.reason_codes


def test_method_decision_change_requires_a_new_method_decision() -> None:
    result = _evaluate(_decision(), _decision(method_decision_ref="MD:SH01-v2"), _request(), _request())
    assert result.allowed is False
    assert result.disposition is RetryDisposition.NEW_METHOD_DECISION_REQUIRED


def test_request_semantics_drift_blocks_retry_even_with_same_ed_id() -> None:
    result = _evaluate(_decision(), _decision(request_semantics_hash="s" * 16), _request(), _request())
    assert result.allowed is False
    assert "REQUEST_SEMANTICS_MISMATCH" in result.reason_codes


def test_mutable_alias_without_revision_proof_blocks_same_execution_retry() -> None:
    mutable = _decision(execution_identity_stability=ExecutionIdentityStability.MUTABLE_ALIAS)
    result = _evaluate(mutable, mutable, _request(), _request())
    assert result.allowed is False
    assert "MUTABLE_ALIAS_NO_REVISION_PROOF" in result.reason_codes


def test_mutable_alias_with_revision_proof_may_retry() -> None:
    mutable = _decision(
        execution_identity_stability=ExecutionIdentityStability.MUTABLE_ALIAS,
        resolved_model_or_tool_revision="rev-2026-09-01",
    )
    result = _evaluate(mutable, mutable, _request(), _request())
    assert result.allowed is True


def test_ambiguous_side_effect_without_idempotency_requires_human_action() -> None:
    result = _evaluate(_decision(), _decision(), _request(), _request(), ambiguous=True, idempotent=False)
    assert result.allowed is False
    assert result.disposition is RetryDisposition.HUMAN_ACTION_REQUIRED
    assert "AMBIGUOUS_SIDE_EFFECT_NO_IDEMPOTENCY" in result.reason_codes


def test_ambiguous_side_effect_with_idempotency_still_allows_retry() -> None:
    result = _evaluate(_decision(), _decision(), _request(), _request(), ambiguous=True, idempotent=True)
    assert result.allowed is True


def test_compiled_request_payload_drift_blocks_retry() -> None:
    result = _evaluate(_decision(), _decision(), _request(), _request(payload={"instruction": "different"}))
    assert result.allowed is False
    assert "REQUEST_FINGERPRINT_MISMATCH" in result.reason_codes


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

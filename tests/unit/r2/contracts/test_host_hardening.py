from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from r2.contracts.host_hardening import (
    AttemptLeaseFence,
    AttemptSnapshot,
    CommandReceipt,
    ExecutionAttemptState,
    OperatorResolutionAction,
    OperatorResolutionReceipt,
    PersistedProviderObservation,
    PlannedExecutionAttempt,
    ProviderCapabilityProfile,
    ProviderIdempotencyMode,
    ProviderNotFoundSemantics,
    ProviderObservation,
    ProviderObservationKind,
    ProviderRouteSnapshot,
    command_receipt_result_envelope,
)

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)

ROUTE = ProviderRouteSnapshot(
    provider_id="acme-video",
    provider_account_ref="acct-1",
    provider_model_id="acme-v3",
    backend_model_id="acme-video-v3",
    endpoint_id="ep-1",
    submitted_base_url="https://api.acme.example/v3",
    adapter_version="1.0.0",
    capability_profile_ref="acme-video-v3@1.0.0",
)


def _capability(**overrides: object) -> ProviderCapabilityProfile:
    defaults: dict[str, object] = {
        "ref": "acme-video-v3@1.0.0",
        "provider_id": "acme-video",
        "api_version": "2026-01-01",
        "adapter_version": "1.0.0",
        "idempotency_mode": ProviderIdempotencyMode.NATIVE_TOKEN,
        "token_scope": None,
        "token_scope_value": None,
        "token_ttl_seconds": None,
        "not_found_semantics": ProviderNotFoundSemantics.NON_AUTHORITATIVE,
        "lookup_settling_window_seconds": None,
        "supports_poll": True,
        "supports_cancel": True,
        "supports_lookup": False,
        "provider_sequence_is_monotonic": False,
        "evidence_digest": "sha256:" + "a" * 64,
    }
    defaults.update(overrides)
    return ProviderCapabilityProfile(**defaults)


def _attempt_snapshot(**overrides: object) -> AttemptSnapshot:
    defaults: dict[str, object] = {
        "execution_id": "exec-1",
        "task_id": "task-1",
        "attempt_no": 1,
        "request_digest": "sha256:" + "b" * 64,
        "route": ROUTE,
        "client_token": "exec-1",
        "provider_job_id": None,
        "state": ExecutionAttemptState.PLANNED,
        "state_version": 1,
        "lease_owner": None,
        "lease_token": None,
        "lease_expires_at": None,
        "created_at": NOW,
        "updated_at": NOW,
        "submitted_at": None,
        "last_observed_at": None,
        "terminal_at": None,
    }
    defaults.update(overrides)
    return AttemptSnapshot(**defaults)


def test_provider_capability_profile_rejects_supports_webhook_true() -> None:
    with pytest.raises(ValidationError):
        _capability(supports_webhook=True)


def test_provider_capability_profile_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ProviderCapabilityProfile(**{**_capability().model_dump(), "unexpected_field": "x"})


def test_provider_capability_profile_defaults_supports_webhook_false() -> None:
    assert _capability().supports_webhook is False


def test_attempt_snapshot_is_frozen() -> None:
    snapshot = _attempt_snapshot()
    with pytest.raises(ValidationError):
        snapshot.state = ExecutionAttemptState.ACCEPTED


def test_attempt_snapshot_requires_timezone_aware_timestamps() -> None:
    with pytest.raises(ValidationError):
        _attempt_snapshot(created_at=datetime(2026, 9, 16, 12, 0))  # naive


def test_planned_execution_attempt_requires_attempt_no_at_least_one() -> None:
    with pytest.raises(ValidationError):
        PlannedExecutionAttempt(
            execution_id="exec-1",
            task_id="task-1",
            attempt_no=0,
            request_digest="sha256:" + "b" * 64,
            route=ROUTE,
            client_token=None,
            trace_id_at_creation=None,
            created_at=NOW,
        )


def test_attempt_lease_fence_requires_token_at_least_one() -> None:
    with pytest.raises(ValidationError):
        AttemptLeaseFence(owner="worker-1", token=0)


def test_operator_resolution_receipt_round_trips_bind_remote_job() -> None:
    receipt = OperatorResolutionReceipt(
        resolution_id="resolution-1",
        execution_id="exec-1",
        expected_attempt_version=3,
        operator_id="operator-1",
        action=OperatorResolutionAction.BIND_REMOTE_JOB,
        resolved_state=ExecutionAttemptState.ACCEPTED,
        provider_job_id="remote-job-1",
        terminal_kind=None,
        evidence_digest="sha256:" + "c" * 64,
        resolved_at=NOW,
    )
    assert receipt.resolved_state is ExecutionAttemptState.ACCEPTED


def test_persisted_provider_observation_requires_received_seq_at_least_one() -> None:
    observation = ProviderObservation(
        observation_id="obs-1",
        kind=ProviderObservationKind.ACCEPTED,
        observed_at=NOW,
        provider_sequence=None,
        provider_job_id="remote-job-1",
        reason_code=None,
        evidence_digest="sha256:" + "d" * 64,
    )
    with pytest.raises(ValidationError):
        PersistedProviderObservation(observation=observation, received_seq=0, received_at=NOW)


def test_command_receipt_result_envelope_matches_the_spec_shape() -> None:
    envelope = command_receipt_result_envelope(task_id="task-1", result={"ok": True})
    assert envelope == {"schema_version": 1, "task_id": "task-1", "result": {"ok": True}}


def test_command_receipt_is_frozen_and_rejects_extra_fields() -> None:
    receipt = CommandReceipt(
        actor_scope="user:alice/project:demo",
        command_id="cmd-1",
        command_digest="sha256:" + "e" * 64,
        task_id="task-1",
        result_digest="sha256:" + "f" * 64,
        created_at=NOW,
    )
    with pytest.raises(ValidationError):
        receipt.command_id = "cmd-2"
    with pytest.raises(ValidationError):
        CommandReceipt(**{**receipt.model_dump(), "unexpected_field": "x"})

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from r2.contracts.host_hardening import (
    TERMINAL_ATTEMPT_STATES,
    AttemptSnapshot,
    ExecutionAttemptState,
    PersistedProviderObservation,
    ProviderCapabilityProfile,
    ProviderIdempotencyMode,
    ProviderNotFoundSemantics,
    ProviderObservation,
    ProviderObservationKind,
    ProviderRouteSnapshot,
)
from r2.host_hardening.transitions import (
    LEGAL_TRANSITIONS,
    AttemptIdentityMismatch,
    fold_observation,
    is_legal_transition,
    validate_exact_replay,
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

# frozenset iteration order is hash-seed dependent (PYTHONHASHSEED varies per
# process), so pytest-xdist workers would otherwise collect these parametrize IDs
# in different orders and fail the "different tests collected" cross-check. Sort
# by name so every worker process sees the identical, deterministic sequence.
ALL_LEGAL_EDGES: list[tuple[ExecutionAttemptState, ExecutionAttemptState]] = sorted(
    ((state, target) for state, targets in LEGAL_TRANSITIONS.items() for target in targets),
    key=lambda pair: (pair[0].value, pair[1].value),
)

# Every (from, to) pair NOT in LEGAL_TRANSITIONS, sampled across all states -- this is
# the exhaustive complement of ALL_LEGAL_EDGES over ExecutionAttemptState x itself.
ALL_ILLEGAL_EDGES: list[tuple[ExecutionAttemptState, ExecutionAttemptState]] = sorted(
    (
        (state, target)
        for state in ExecutionAttemptState
        for target in ExecutionAttemptState
        if target not in LEGAL_TRANSITIONS[state] and target != state
    ),
    key=lambda pair: (pair[0].value, pair[1].value),
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
        "state": ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN,
        "state_version": 1,
        "lease_owner": None,
        "lease_token": None,
        "lease_expires_at": None,
        "created_at": NOW,
        "updated_at": NOW,
        "submitted_at": NOW,
        "last_observed_at": None,
        "terminal_at": None,
    }
    defaults.update(overrides)
    return AttemptSnapshot(**defaults)


def _persisted(
    kind: ProviderObservationKind,
    *,
    observed_at: datetime = NOW,
    provider_job_id: str | None = None,
    received_seq: int = 1,
) -> PersistedProviderObservation:
    return PersistedProviderObservation(
        observation=ProviderObservation(
            observation_id=f"obs-{kind.value}-{received_seq}",
            kind=kind,
            observed_at=observed_at,
            provider_sequence=None,
            provider_job_id=provider_job_id,
            reason_code=None,
            evidence_digest="sha256:" + "c" * 64,
        ),
        received_seq=received_seq,
        received_at=observed_at,
    )


# --- table-driven legal/illegal edge coverage ------------------------------------------


@pytest.mark.parametrize(("state", "target"), ALL_LEGAL_EDGES)
def test_every_legal_edge_is_legal(state: ExecutionAttemptState, target: ExecutionAttemptState) -> None:
    assert is_legal_transition(state, target) is True


@pytest.mark.parametrize(("state", "target"), ALL_ILLEGAL_EDGES)
def test_every_illegal_edge_is_illegal(state: ExecutionAttemptState, target: ExecutionAttemptState) -> None:
    assert is_legal_transition(state, target) is False


@pytest.mark.parametrize("state", sorted(TERMINAL_ATTEMPT_STATES, key=str))
def test_terminal_states_have_no_outgoing_edges(state: ExecutionAttemptState) -> None:
    assert LEGAL_TRANSITIONS[state] == frozenset()


def test_needs_operator_is_not_terminal_but_has_no_worker_entry_in_legal_transitions_from_itself() -> None:
    # NEEDS_OPERATOR is non-terminal (spec 4.2): it has outgoing edges, but only an
    # exact OperatorResolutionReceipt may traverse them (enforced by the repository,
    # a later task) -- this module only proves the edges exist.
    assert ExecutionAttemptState.NEEDS_OPERATOR not in TERMINAL_ATTEMPT_STATES
    assert LEGAL_TRANSITIONS[ExecutionAttemptState.NEEDS_OPERATOR] != frozenset()


# --- direct unknown-to-terminal observation folds ---------------------------------------


@pytest.mark.parametrize(
    ("kind", "expected_state"),
    [
        (ProviderObservationKind.SUCCEEDED, ExecutionAttemptState.SUCCEEDED),
        (ProviderObservationKind.FAILED, ExecutionAttemptState.FAILED),
        (ProviderObservationKind.CANCELLED, ExecutionAttemptState.CANCELLED),
        (ProviderObservationKind.ACCEPTED, ExecutionAttemptState.ACCEPTED),
        (ProviderObservationKind.RUNNING, ExecutionAttemptState.RUNNING),
    ],
)
def test_unknown_attempt_takes_a_direct_edge_to_its_observed_remote_state(
    kind: ProviderObservationKind, expected_state: ExecutionAttemptState
) -> None:
    snapshot = _attempt_snapshot(state=ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN)
    result = fold_observation(snapshot, _persisted(kind, provider_job_id="remote-1"), _capability())
    assert result.state is expected_state
    assert result.state_version == snapshot.state_version + 1
    assert result.provider_job_id == "remote-1"


def test_observation_never_moves_state_backwards() -> None:
    snapshot = _attempt_snapshot(state=ExecutionAttemptState.RUNNING)
    result = fold_observation(snapshot, _persisted(ProviderObservationKind.ACCEPTED), _capability())
    assert result == snapshot  # ACCEPTED after RUNNING is backwards: ignored


def test_observation_never_leaves_a_terminal_state() -> None:
    snapshot = _attempt_snapshot(state=ExecutionAttemptState.SUCCEEDED, terminal_at=NOW)
    result = fold_observation(snapshot, _persisted(ProviderObservationKind.RUNNING), _capability())
    assert result == snapshot


# --- both NOT_FOUND policies -------------------------------------------------------------


def test_not_found_within_the_settling_window_remains_unknown() -> None:
    snapshot = _attempt_snapshot(state=ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN, submitted_at=NOW)
    capability = _capability(
        not_found_semantics=ProviderNotFoundSemantics.AUTHORITATIVE_AFTER_SETTLING_WINDOW,
        lookup_settling_window_seconds=300,
    )
    observation = _persisted(ProviderObservationKind.NOT_FOUND, observed_at=NOW + timedelta(seconds=60))
    result = fold_observation(snapshot, observation, capability)
    assert result == snapshot


def test_not_found_after_the_window_becomes_failed_before_acceptance_when_authoritative() -> None:
    snapshot = _attempt_snapshot(state=ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN, submitted_at=NOW)
    capability = _capability(
        not_found_semantics=ProviderNotFoundSemantics.AUTHORITATIVE_AFTER_SETTLING_WINDOW,
        lookup_settling_window_seconds=300,
    )
    observation = _persisted(ProviderObservationKind.NOT_FOUND, observed_at=NOW + timedelta(seconds=600))
    result = fold_observation(snapshot, observation, capability)
    assert result.state is ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE


def test_not_found_after_the_window_becomes_needs_operator_when_non_authoritative() -> None:
    snapshot = _attempt_snapshot(state=ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN, submitted_at=NOW)
    capability = _capability(
        not_found_semantics=ProviderNotFoundSemantics.NON_AUTHORITATIVE,
        lookup_settling_window_seconds=300,
    )
    observation = _persisted(ProviderObservationKind.NOT_FOUND, observed_at=NOW + timedelta(seconds=600))
    result = fold_observation(snapshot, observation, capability)
    assert result.state is ExecutionAttemptState.NEEDS_OPERATOR


def test_not_found_with_no_declared_window_is_immediately_authoritative() -> None:
    snapshot = _attempt_snapshot(state=ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN, submitted_at=NOW)
    capability = _capability(
        not_found_semantics=ProviderNotFoundSemantics.AUTHORITATIVE_AFTER_SETTLING_WINDOW,
        lookup_settling_window_seconds=None,
    )
    result = fold_observation(snapshot, _persisted(ProviderObservationKind.NOT_FOUND), capability)
    assert result.state is ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE


def test_authoritative_not_found_falls_back_to_needs_operator_when_failed_before_acceptance_is_illegal() -> None:
    # CANCEL_OUTCOME_UNKNOWN has no FAILED_BEFORE_ACCEPTANCE edge (the attempt was
    # already submitted, by definition, to have reached a cancel outcome) -- the fold
    # fails closed to NEEDS_OPERATOR instead of silently dropping the fact.
    snapshot = _attempt_snapshot(state=ExecutionAttemptState.CANCEL_OUTCOME_UNKNOWN, submitted_at=NOW)
    capability = _capability(
        not_found_semantics=ProviderNotFoundSemantics.AUTHORITATIVE_AFTER_SETTLING_WINDOW,
        lookup_settling_window_seconds=None,
    )
    result = fold_observation(snapshot, _persisted(ProviderObservationKind.NOT_FOUND), capability)
    assert result.state is ExecutionAttemptState.NEEDS_OPERATOR


# --- conflicting terminal facts and duplicate observations ------------------------------


def test_conflicting_terminal_facts_never_replace_the_first_committed_terminal_state() -> None:
    snapshot = _attempt_snapshot(state=ExecutionAttemptState.SUCCEEDED, terminal_at=NOW)
    conflicting = _persisted(ProviderObservationKind.FAILED, observed_at=NOW + timedelta(seconds=5))
    result = fold_observation(snapshot, conflicting, _capability())
    assert result.state is ExecutionAttemptState.SUCCEEDED
    assert result == snapshot


def test_duplicate_observation_id_reapplied_is_a_no_op() -> None:
    snapshot = _attempt_snapshot(state=ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN)
    observation = _persisted(ProviderObservationKind.ACCEPTED, provider_job_id="remote-1")
    once = fold_observation(snapshot, observation, _capability())
    twice = fold_observation(once, observation, _capability())
    assert twice == once


# --- opaque-ID / hash validation (plan() exact replay) -----------------------------------


def test_exact_replay_with_identical_identity_fields_does_not_raise() -> None:
    existing = _attempt_snapshot()
    result = validate_exact_replay(
        existing=existing,
        execution_id=existing.execution_id,
        request_digest=existing.request_digest,
        route=existing.route,
        client_token=existing.client_token,
        created_at=existing.created_at,
    )
    assert result is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"execution_id": "different"},
        {"request_digest": "sha256:" + "0" * 64},
        {"client_token": "different-token"},
        {"created_at": NOW + timedelta(seconds=1)},
    ],
)
def test_exact_replay_raises_on_any_unequal_identity_field(overrides: dict[str, object]) -> None:
    existing = _attempt_snapshot()
    kwargs: dict[str, object] = {
        "execution_id": existing.execution_id,
        "request_digest": existing.request_digest,
        "route": existing.route,
        "client_token": existing.client_token,
        "created_at": existing.created_at,
    }
    kwargs.update(overrides)
    with pytest.raises(AttemptIdentityMismatch):
        validate_exact_replay(existing=existing, **kwargs)


def test_exact_replay_raises_on_a_different_route() -> None:
    existing = _attempt_snapshot()
    different_route = ROUTE.model_copy(update={"provider_account_ref": "acct-2"})
    with pytest.raises(AttemptIdentityMismatch):
        validate_exact_replay(
            existing=existing,
            execution_id=existing.execution_id,
            request_digest=existing.request_digest,
            route=different_route,
            client_token=existing.client_token,
            created_at=existing.created_at,
        )

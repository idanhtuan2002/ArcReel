"""Pure ExecutionAttempt transition table and monotonic observation fold
(spec section 4.2; plan Task 1). No I/O, no persistence, no clock reads: every
function here is a deterministic value transformation so the repository layer
(a later task) can unit test recovery behavior without a database.
"""

from __future__ import annotations

from r2.contracts.host_hardening import (
    TERMINAL_ATTEMPT_STATES,
    AttemptSnapshot,
    ExecutionAttemptState,
    PersistedProviderObservation,
    ProviderCapabilityProfile,
    ProviderNotFoundSemantics,
    ProviderObservationKind,
    ProviderRouteSnapshot,
)

# --- legal transition table (spec section 4.2) ----------------------------------------

LEGAL_TRANSITIONS: dict[ExecutionAttemptState, frozenset[ExecutionAttemptState]] = {
    ExecutionAttemptState.PLANNED: frozenset(
        {ExecutionAttemptState.SUBMITTING, ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE}
    ),
    ExecutionAttemptState.SUBMITTING: frozenset(
        {
            ExecutionAttemptState.ACCEPTED,
            ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN,
            ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE,
        }
    ),
    ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN: frozenset(
        {
            ExecutionAttemptState.ACCEPTED,
            ExecutionAttemptState.RUNNING,
            ExecutionAttemptState.SUCCEEDED,
            ExecutionAttemptState.FAILED,
            ExecutionAttemptState.CANCELLED,
            ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE,
            ExecutionAttemptState.NEEDS_OPERATOR,
        }
    ),
    ExecutionAttemptState.ACCEPTED: frozenset(
        {
            ExecutionAttemptState.RUNNING,
            ExecutionAttemptState.SUCCEEDED,
            ExecutionAttemptState.FAILED,
            ExecutionAttemptState.CANCEL_REQUESTED,
        }
    ),
    ExecutionAttemptState.RUNNING: frozenset(
        {
            ExecutionAttemptState.SUCCEEDED,
            ExecutionAttemptState.FAILED,
            ExecutionAttemptState.CANCEL_REQUESTED,
        }
    ),
    ExecutionAttemptState.CANCEL_REQUESTED: frozenset(
        {
            ExecutionAttemptState.CANCELLED,
            ExecutionAttemptState.SUCCEEDED,
            ExecutionAttemptState.FAILED,
            ExecutionAttemptState.CANCEL_OUTCOME_UNKNOWN,
        }
    ),
    ExecutionAttemptState.CANCEL_OUTCOME_UNKNOWN: frozenset(
        {
            ExecutionAttemptState.CANCELLED,
            ExecutionAttemptState.SUCCEEDED,
            ExecutionAttemptState.FAILED,
            ExecutionAttemptState.NEEDS_OPERATOR,
        }
    ),
    ExecutionAttemptState.NEEDS_OPERATOR: frozenset(
        {
            ExecutionAttemptState.ACCEPTED,
            ExecutionAttemptState.RUNNING,
            ExecutionAttemptState.SUCCEEDED,
            ExecutionAttemptState.FAILED,
            ExecutionAttemptState.CANCELLED,
            ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE,
        }
    ),
    # Terminal states have no outgoing edges.
    ExecutionAttemptState.SUCCEEDED: frozenset(),
    ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE: frozenset(),
    ExecutionAttemptState.FAILED: frozenset(),
    ExecutionAttemptState.CANCELLED: frozenset(),
}

assert set(LEGAL_TRANSITIONS) == set(ExecutionAttemptState)

_OBSERVATION_KIND_TO_STATE: dict[ProviderObservationKind, ExecutionAttemptState] = {
    ProviderObservationKind.ACCEPTED: ExecutionAttemptState.ACCEPTED,
    ProviderObservationKind.RUNNING: ExecutionAttemptState.RUNNING,
    ProviderObservationKind.SUCCEEDED: ExecutionAttemptState.SUCCEEDED,
    ProviderObservationKind.FAILED: ExecutionAttemptState.FAILED,
    ProviderObservationKind.CANCELLED: ExecutionAttemptState.CANCELLED,
}


def is_legal_transition(current: ExecutionAttemptState, target: ExecutionAttemptState) -> bool:
    return target in LEGAL_TRANSITIONS[current]


class AttemptIdentityMismatch(ValueError):
    """Raised when an exact ``plan()`` replay's identity fields disagree with the
    already-persisted attempt (spec section 4.1)."""


def validate_exact_replay(
    *,
    existing: AttemptSnapshot,
    execution_id: str,
    request_digest: str,
    route: ProviderRouteSnapshot,
    client_token: str | None,
    created_at: object,
) -> None:
    """Exact replay of ``plan()`` requires equality of every field the spec names;
    any unequal field raises ``AttemptIdentityMismatch``. Pure and side-effect free:
    the repository (a later task) is responsible for the atomic read-compare-return
    this function's boolean logic backs."""
    mismatches: list[str] = []
    if existing.execution_id != execution_id:
        mismatches.append("execution_id")
    if existing.request_digest != request_digest:
        mismatches.append("request_digest")
    if existing.route != route:
        mismatches.append("route")
    if existing.client_token != client_token:
        mismatches.append("client_token")
    if existing.created_at != created_at:
        mismatches.append("created_at")
    if mismatches:
        raise AttemptIdentityMismatch(
            f"exact replay of execution {existing.execution_id!r} disagrees on: {sorted(mismatches)}"
        )


def _not_found_target(
    *, snapshot: AttemptSnapshot, observation: PersistedProviderObservation, capability: ProviderCapabilityProfile
) -> ExecutionAttemptState | None:
    reference_time = snapshot.submitted_at or snapshot.created_at
    window_seconds = capability.lookup_settling_window_seconds
    if window_seconds is None:
        elapsed = True
    else:
        from datetime import timedelta

        elapsed = observation.observation.observed_at >= reference_time + timedelta(seconds=window_seconds)

    if not elapsed:
        return None  # still within the qualified settling window: remains unknown

    if capability.not_found_semantics == ProviderNotFoundSemantics.AUTHORITATIVE_AFTER_SETTLING_WINDOW:
        candidate = ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE
    else:
        candidate = ExecutionAttemptState.NEEDS_OPERATOR

    if is_legal_transition(snapshot.state, candidate):
        return candidate
    # FAILED_BEFORE_ACCEPTANCE is illegal from a state that implies the attempt was
    # already submitted (e.g. CANCEL_OUTCOME_UNKNOWN): fail closed to an operator
    # pause rather than silently dropping the authoritative NOT_FOUND fact.
    if is_legal_transition(snapshot.state, ExecutionAttemptState.NEEDS_OPERATOR):
        return ExecutionAttemptState.NEEDS_OPERATOR
    return None


def fold_observation(
    snapshot: AttemptSnapshot,
    observation: PersistedProviderObservation,
    capability: ProviderCapabilityProfile,
) -> AttemptSnapshot:
    """Monotonic provider-observation fold (spec section 4.2).

    An observation cannot move attempt state backwards, invent an intermediate
    ``ACCEPTED`` step, or leave a terminal state. Applying the identical
    observation to its own already-applied result is a no-op, which is what makes
    a duplicate ``observation_id`` a no-op without this function needing to track
    observation history itself -- the caller (repository, a later task) supplies
    the current snapshot either way.
    """
    kind = observation.observation.kind

    if kind is ProviderObservationKind.NOT_FOUND:
        target = _not_found_target(snapshot=snapshot, observation=observation, capability=capability)
    else:
        target = _OBSERVATION_KIND_TO_STATE[kind]

    if target is None or target == snapshot.state:
        return snapshot

    if snapshot.state in TERMINAL_ATTEMPT_STATES:
        # Conflicting terminal facts never replace the first committed terminal
        # state. The caller compares its own pre/post snapshot to notice the
        # conflict and append an AttemptIntegrityIncident; this fold only ever
        # returns the unchanged, already-terminal truth.
        return snapshot

    if not is_legal_transition(snapshot.state, target):
        # Out-of-order or backwards fact: ignored, never applied.
        return snapshot

    provider_job_id = observation.observation.provider_job_id or snapshot.provider_job_id
    terminal_at = observation.received_at if target in TERMINAL_ATTEMPT_STATES else snapshot.terminal_at

    return snapshot.model_copy(
        update={
            "state": target,
            "state_version": snapshot.state_version + 1,
            "provider_job_id": provider_job_id,
            "last_observed_at": observation.observation.observed_at,
            "terminal_at": terminal_at,
            "updated_at": observation.received_at,
        }
    )


__all__ = [
    "LEGAL_TRANSITIONS",
    "AttemptIdentityMismatch",
    "fold_observation",
    "is_legal_transition",
    "validate_exact_replay",
]

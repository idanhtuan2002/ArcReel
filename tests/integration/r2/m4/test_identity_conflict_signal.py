"""A CONFLICTED visual identity does not fail silently.

The Gate-1 block emits a ``FailureRecord(HUMAN_ACTION_REQUIRED)`` and a
correlated ``ProductionEvent`` review signal, not a bare return.
"""

from __future__ import annotations

import dataclasses

from r2.contracts import (
    FailureDomain,
    FailureRecord,
    IdentityConstraint,
    IdentityScopeType,
    IdentityStrength,
    ProductionEvent,
    ReadinessState,
    RetryDisposition,
    VisualIdentityProfile,
)


def _conflicting_profile(scene_id: str) -> VisualIdentityProfile:
    return VisualIdentityProfile(
        id="VIP-CONFLICT",
        schema_version="1",
        version=1,
        semantic_character_ref="character:lead",
        scope_type=IdentityScopeType.SCENE,
        scope_ref=scene_id,
        identity_constraints=[
            IdentityConstraint(
                semantic_key="hairstyle",
                strength=IdentityStrength.LOCKED,
                semantic_value="waist-length braid",
            )
        ],
    )


async def test_identity_conflict_emits_failure_record_and_production_event(golden_12, pipeline) -> None:
    base = golden_12.by_id("SH05")
    case = dataclasses.replace(base, identity_profiles=(*base.identity_profiles, _conflicting_profile(base.scene.id)))

    result = await pipeline(case)

    assert result.readiness is not None
    assert result.readiness.state is ReadinessState.BLOCKED
    assert result.readiness.blocked_reason == "IDENTITY_CONFLICT"

    assert isinstance(result.failure, FailureRecord)
    assert result.failure.domain is FailureDomain.READINESS
    assert result.failure.reason_code == "IDENTITY_CONFLICT"
    assert result.failure.retry_disposition is RetryDisposition.HUMAN_ACTION_REQUIRED
    assert result.failure.target_ref == case.shot.id

    events = [e for e in result.events if isinstance(e, ProductionEvent)]
    assert any(
        e.reason_code == "IDENTITY_CONFLICT" and e.target_ref == case.shot.id and e.event_type == "FAILURE"
        for e in events
    )
    # The pipeline stopped before method routing.
    assert result.method_decision is None


async def test_clean_identity_case_emits_no_failure_signal(golden_12, pipeline) -> None:
    result = await pipeline(golden_12.by_id("SH05"))
    assert result.failure is None
    assert result.events == []
